from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from ironsbot.core.outbound import BinaryImagePart, DeliveryFailureKind
from ironsbot.integrations.storage.bilibili_delivery_ledger import (
    SqliteDynamicDeliveryLedger,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase
from ironsbot.services.bilibili.delivery_preparation import preparation_failure
from ironsbot.services.bilibili.media_preparation import (
    MediaPreparationError,
    prepare_shared_media,
)
from ironsbot.services.bilibili.target_models import BiliPushTargets
from ironsbot.services.messaging.image_collage import (
    ImageCollageError,
    ImageCollageService,
)
from tests.test_bilibili_outbound_delivery import _item
from tests.test_bilibili_unit_retries import TARGET

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_URLS = ("https://example.com/a.png?secret=hidden", "https://example.com/b.png")
_FOUR = 4
_SECOND = 2


def item() -> dict[str, Any]:
    value = _item()
    value["modules"]["module_dynamic"]["major"]["opus"]["pics"] = [
        {"url": url} for url in _URLS
    ]
    return value


def ledger_at(path: Path) -> SqliteDynamicDeliveryLedger:
    ledger = SqliteDynamicDeliveryLedger(path)
    ledger.prepare(
        item(), int(time.time()), 123, BiliPushTargets([TARGET], [], [], []), ()
    )
    return ledger


def render(image_bytes: Sequence[bytes], **_kwargs: Any) -> bytes:
    return b"collage:" + b"".join(image_bytes)


@pytest.mark.asyncio
async def test_shared_preparation_survives_waiter_cancel(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path / "ledger.sqlite")
    entered, release = asyncio.Event(), asyncio.Event()
    seen: Counter[str] = Counter()

    async def fetch(url: str, _limit: int) -> bytes:
        seen[url] += 1
        entered.set()
        await release.wait()
        return url.encode()

    collage = ImageCollageService(fetch, render)
    first = asyncio.create_task(
        prepare_shared_media(item(), "1", collage, ledger, combine=True)
    )
    await entered.wait()
    second = asyncio.create_task(
        prepare_shared_media(
            item(),
            "1",
            replace(collage),
            SqliteDynamicDeliveryLedger(ledger.path),
            combine=True,
        )
    )
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    result = await second
    assert result is not None and len(result.parts) == 1
    assert seen == Counter(dict.fromkeys(_URLS, 1))
    found, frozen = ledger.load_media("1")
    assert found and frozen == result


@pytest.mark.asyncio
async def test_retry_only_missing_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = ledger_at(tmp_path / "ledger.sqlite")
    seen: Counter[str] = Counter()
    sleep = asyncio.sleep

    async def fast_sleep(_delay: float) -> None:
        await sleep(0)

    monkeypatch.setattr(
        "ironsbot.services.bilibili.media_preparation.asyncio.sleep", fast_sleep
    )

    async def fetch(url: str, _limit: int) -> bytes:
        seen[url] += 1
        if url == _URLS[1] and seen[url] == 1:
            error = ImageCollageError.download_failed()
            error.retryable = True
            raise error
        return url.encode()

    await prepare_shared_media(
        item(), "1", ImageCollageService(fetch, render), ledger, combine=True
    )
    assert seen == Counter({_URLS[0]: 1, _URLS[1]: 2})
    with SqliteDatabase(ledger.path).connect() as db:
        attempts, status = db.execute(
            "SELECT attempts,status FROM media_preparations"
        ).fetchone()
    assert attempts == _SECOND and status == "complete"


@pytest.mark.asyncio
async def test_original_fallback_is_complete_ordered_and_diagnosed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ledger = ledger_at(tmp_path / "ledger.sqlite")

    async def fetch(url: str, _limit: int) -> bytes:
        return url.encode()

    def fail_render(image_bytes: Sequence[bytes], **_kwargs: Any) -> bytes:
        assert image_bytes
        raise ImageCollageError.render_failed()

    message = await prepare_shared_media(
        item(), "1", ImageCollageService(fetch, fail_render), ledger, combine=True
    )
    assert message is not None
    assert [
        part.content for part in message.parts if isinstance(part, BinaryImagePart)
    ] == [url.encode() for url in _URLS]
    with SqliteDatabase(ledger.path).connect() as db:
        status, diagnostics = db.execute(
            "SELECT status,diagnostics FROM media_preparations"
        ).fetchone()
    assert (
        status == "degraded" and "compose_failed" in json.loads(diagnostics)["reasons"]
    )
    assert "secret=hidden" not in caplog.text


@pytest.mark.asyncio
async def test_missing_original_is_not_frozen(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path / "ledger.sqlite")

    async def fetch(url: str, _limit: int) -> bytes:
        if url == _URLS[1]:
            raise ImageCollageError.decode_failed()
        return url.encode()

    with pytest.raises(MediaPreparationError):
        await prepare_shared_media(
            item(), "1", ImageCollageService(fetch, render), ledger, combine=True
        )
    assert ledger.load_media("1") == (False, None)
    assert (
        ledger.load_media_source("1", hashlib.sha256(_URLS[0].encode()).hexdigest())
        == _URLS[0].encode()
    )


def test_media_budget_and_sources_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite"
    ledger = ledger_at(path)
    assert ledger.begin_media_preparation("1", "fingerprint")[0] == 1
    ledger.save_media_source("1", "source", b"saved")
    restarted = SqliteDynamicDeliveryLedger(path)
    assert restarted.load_media_source("1", "source") == b"saved"
    for expected in range(2, _FOUR + 1):
        assert restarted.begin_media_preparation("1", "fingerprint")[0] == expected
    assert SqliteDynamicDeliveryLedger(path).begin_media_preparation(
        "1", "fingerprint"
    ) == (0, 0.0)
    with pytest.raises(ValueError, match="identity"):
        restarted.begin_media_preparation("1", "changed")


def test_expired_budget_never_renews(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path / "ledger.sqlite")
    ledger.begin_media_preparation("1", "fingerprint")
    with SqliteDatabase(ledger.path).connect() as db:
        db.execute("UPDATE media_preparations SET deadline=0")
    assert ledger.begin_media_preparation("1", "fingerprint") == (0, 0.0)


def test_source_references_protect_cleanup_and_detect_corruption(
    tmp_path: Path,
) -> None:
    ledger = ledger_at(tmp_path / "ledger.sqlite")
    ledger.save_media_source("1", "source", b"saved")
    assert ledger.cleanup_media().deleted_files == 0
    (ledger.media_root / hashlib.sha256(b"saved").hexdigest()).write_bytes(b"changed")
    with pytest.raises(ValueError, match="mismatch"):
        ledger.load_media_source("1", "source")


@pytest.mark.asyncio
async def test_four_shared_attempts_not_reopened_by_new_sender(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = ledger_at(tmp_path / "ledger.sqlite")
    seen: Counter[str] = Counter()
    sleep = asyncio.sleep

    async def fast_sleep(_delay: float) -> None:
        await sleep(0)

    monkeypatch.setattr(
        "ironsbot.services.bilibili.media_preparation.asyncio.sleep", fast_sleep
    )

    async def fetch(url: str, _limit: int) -> bytes:
        seen[url] += 1
        if url == _URLS[1]:
            raise TimeoutError
        return url.encode()

    collage = ImageCollageService(fetch, render)
    for _ in range(2):
        with pytest.raises(MediaPreparationError) as failure:
            await prepare_shared_media(
                item(),
                "1",
                collage,
                SqliteDynamicDeliveryLedger(ledger.path),
                combine=True,
            )
        assert (
            preparation_failure(failure.value).failure_kind
            is DeliveryFailureKind.PERMANENT
        )
    assert seen == Counter({_URLS[0]: 1, _URLS[1]: _FOUR})
    assert ledger.load_media("1") == (False, None)


@pytest.mark.asyncio
async def test_persisted_source_used_by_restarted_preparation(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path / "ledger.sqlite")
    ledger.save_media_source(
        "1", hashlib.sha256(_URLS[0].encode()).hexdigest(), _URLS[0].encode()
    )
    seen = []

    async def fetch(url: str, _limit: int) -> bytes:
        seen.append(url)
        return url.encode()

    await prepare_shared_media(
        item(),
        "1",
        ImageCollageService(fetch, render),
        SqliteDynamicDeliveryLedger(ledger.path),
        combine=True,
    )
    assert seen == [_URLS[1]]


@pytest.mark.asyncio
async def test_existing_deadline_bounds_inflight_preparation(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path / "ledger.sqlite")
    # Set a short committed deadline without changing the production contract.
    fingerprint = hashlib.sha256(("True\n" + "\n".join(_URLS)).encode()).hexdigest()
    ledger.begin_media_preparation("1", fingerprint)
    with SqliteDatabase(ledger.path).connect() as db:
        db.execute("UPDATE media_preparations SET deadline=?", (time.time() + 0.03,))

    async def fetch(_url: str, _limit: int) -> bytes:
        await asyncio.Event().wait()
        return b"unreachable"

    with pytest.raises(MediaPreparationError):
        await asyncio.wait_for(
            prepare_shared_media(
                item(), "1", ImageCollageService(fetch, render), ledger, combine=True
            ),
            1,
        )
    assert ledger.load_media("1") == (False, None)
    with SqliteDatabase(ledger.path).connect() as db:
        deadline, status = db.execute(
            "SELECT deadline,status FROM media_preparations"
        ).fetchone()
    assert deadline < time.time() and status == "failed"


@pytest.mark.asyncio
async def test_mixed_formats_are_not_reported_as_degradation(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path / "ledger.sqlite")

    async def fetch(url: str, _limit: int) -> bytes:
        return b"GIF89a" if url == _URLS[0] else b"static"

    collage = ImageCollageService(
        fetch,
        render,
        inspect_animation=lambda image_bytes: image_bytes.startswith(b"GIF"),
    )
    result = await prepare_shared_media(item(), "1", collage, ledger, combine=True)
    assert result is not None and len(result.parts) == _SECOND
    with SqliteDatabase(ledger.path).connect() as db:
        status = db.execute("SELECT status FROM media_preparations").fetchone()[0]
    assert status == "complete"
