from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.outbound import (
    BinaryImagePart,
    DeliveryFailureKind,
    OutboundMessage,
    SendResult,
)
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.storage.bilibili_delivery_ledger import (
    SqliteDynamicDeliveryLedger,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase
from ironsbot.services.bilibili.outbound_delivery import BilibiliDynamicOutboundSender
from ironsbot.services.bilibili.target_models import BiliPushTargets
from tests.test_bilibili_outbound_delivery import _item
from tests.test_bilibili_unit_retries import TARGET, image_message
from tests.test_proactive_delivery import FakeMessenger, _delivery

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(now=time.time(), waits=[])
    original_sleep = asyncio.sleep

    async def sleep(delay: float) -> None:
        state.waits.append(delay)
        state.now += delay
        await original_sleep(0)

    monkeypatch.setattr(
        "ironsbot.integrations.storage.bilibili_delivery_ledger.time",
        SimpleNamespace(time=lambda: state.now),
    )
    monkeypatch.setattr(
        "ironsbot.services.bilibili.outbound_delivery.asyncio.sleep", sleep
    )
    return state


@pytest.mark.asyncio
async def test_preparation_recovery_expands_once_and_stops_scanning(
    tmp_path: Path,
    clock: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    messenger = FakeMessenger()
    delivery, _, subs = _delivery(messenger=messenger)
    notices = AsyncMock()
    sender = BilibiliDynamicOutboundSender(
        delivery, cast("Any", subs), ledger=ledger, admin_notices=notices
    )
    preparations = 0

    async def prepare(
        _self: BilibiliDynamicOutboundSender, _item: dict[str, Any], _id: str
    ) -> OutboundMessage | None:
        nonlocal preparations
        preparations += 1
        if preparations == 1:
            message = "private signed URL must not be logged"
            raise TimeoutError(message)
        return ledger.freeze_media(_id, image_message("https://example.com/one.png"))

    monkeypatch.setattr(
        BilibiliDynamicOutboundSender, "_prepare_frozen_images", prepare
    )
    item = _item()
    other = ConversationRef(Platform.ONEBOT, "group", "101")
    targets = BiliPushTargets([TARGET, other], [], [], [])
    await sender.send(item, int(clock.now), 123, targets)
    assert ledger.state_counts(item["id_str"]) == {"success": 6}
    assert preparations == len(("timeout", "recovered"))
    notices.send_private_to_superusers.assert_not_awaited()
    assert caplog.text.count("Bilibili media preparation failed:") == 1
    assert "private signed URL" not in caplog.text
    original_rounds = ledger.round_count(item["id_str"])
    original_calls = len(messenger.calls)
    for _ in range(8):
        ledger.recover()
        await sender.send(item, int(clock.now), 123, targets, resume=True)
    assert ledger.round_count(item["id_str"]) == original_rounds
    assert len(messenger.calls) == original_calls


@pytest.mark.parametrize(
    ("code", "kind", "expand"),
    [
        ("media_prepare:ImageCollageError", DeliveryFailureKind.RETRYABLE, True),
        ("upload_confirm:11001", DeliveryFailureKind.RETRYABLE, False),
        ("media_prepare:TimeoutError", DeliveryFailureKind.UNCERTAIN, False),
    ],
)
def test_only_proven_preparation_failures_expand(
    tmp_path: Path,
    clock: SimpleNamespace,
    code: str,
    kind: DeliveryFailureKind,
    *,
    expand: bool,
) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    item = _item()
    key = item["id_str"]
    ledger.prepare(item, int(clock.now), 123, BiliPushTargets([TARGET], [], [], []), ())
    assert ledger.claim(key, TARGET, "image")
    ledger.finish(
        key,
        TARGET,
        "image",
        SendResult(
            delivered=False,
            error_code=code,
            failure_kind=kind,
        ),
    )
    ledger.image_units(key, TARGET, 1)
    ledger.image_units(key, TARGET, 1)
    assert ledger.unattempted(key, TARGET, "image:1") is expand


def test_offline_and_empty_cycles_do_not_consume_budget(
    tmp_path: Path,
    clock: SimpleNamespace,
) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    item = _item()
    key = item["id_str"]
    ledger.prepare(item, int(clock.now), 123, BiliPushTargets([TARGET], [], [], []), ())
    for _ in range(8):
        assert ledger.begin_round(key)
        assert ledger.claim(key, TARGET, "link")
        ledger.finish(
            key,
            TARGET,
            "link",
            SendResult(
                delivered=False,
                error_code="account_offline",
                failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
            ),
        )
        ledger.finish_round(key)
        assert ledger.attempts(key, TARGET, "link") == 0
        assert ledger.round_count(key) == 0
    for stage in ("link", "text", "image"):
        ledger.skip_stage(key, TARGET, stage)
    assert not ledger.begin_round(key)


def test_exhausted_units_cannot_open_new_rounds(
    tmp_path: Path,
    clock: SimpleNamespace,
) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    item = _item()
    key = item["id_str"]
    ledger.prepare(item, int(clock.now), 123, BiliPushTargets([TARGET], [], [], []), ())
    with SqliteDatabase(ledger.path).connect() as db:
        db.execute("UPDATE stages SET state='retry',attempts=4")
    for _ in range(8):
        assert not ledger.begin_round(key)
        assert not ledger.claim(key, TARGET, "image")
    assert ledger.round_count(key) == 0


def test_frozen_bytes_survive_disposable_cache_and_reopen(tmp_path: Path) -> None:
    persistent = tmp_path / "data" / "bilibili"
    ledger = SqliteDynamicDeliveryLedger(persistent / "ledger.sqlite")
    message = OutboundMessage((BinaryImagePart(b"frozen", "image/png", "one.png"),))
    ledger.freeze_media("one", message)
    assert ledger.media_root == persistent / "delivery_media"
    cache = tmp_path / "cache"
    cache.mkdir()
    disposable = cache / "render.png"
    disposable.write_bytes(b"disposable")
    disposable.unlink()
    cache.rmdir()
    reopened = SqliteDynamicDeliveryLedger(ledger.path)
    assert reopened.load_media("one") == (True, message)
    for path in ledger.media_root.iterdir():
        path.unlink()
    with pytest.raises(FileNotFoundError):
        reopened.load_media("one")


@pytest.mark.asyncio
async def test_missing_frozen_partial_image_terminates_without_resend(
    tmp_path: Path,
    clock: SimpleNamespace,
) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    item = _item()
    key = item["id_str"]
    targets = BiliPushTargets([TARGET], [], [], [])
    ledger.prepare(item, int(clock.now), 123, targets, ())
    ledger.freeze_media(
        key, OutboundMessage((BinaryImagePart(b"original", "image/png", "one.png"),))
    )
    ledger.image_units(key, TARGET, 2)
    for stage in ("link", "text", "image:1"):
        assert ledger.claim(key, TARGET, stage)
        ledger.finish(key, TARGET, stage, SendResult(delivered=True, message_id=stage))
    for path in ledger.media_root.iterdir():
        path.unlink()
    messenger = FakeMessenger()
    delivery, _, subs = _delivery(messenger=messenger)
    sender = BilibiliDynamicOutboundSender(delivery, cast("Any", subs), ledger=ledger)
    await sender.send(item, int(clock.now), 123, targets, resume=True)
    assert not messenger.calls
    assert ledger.state_counts(key) == {"success": 3, "failed": 1}
    assert not ledger.begin_round(key)


@pytest.mark.asyncio
async def test_preparation_budget_survives_repeated_recovery(
    tmp_path: Path,
    clock: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    messenger = FakeMessenger()
    delivery, _, subs = _delivery(messenger=messenger)
    sender = BilibiliDynamicOutboundSender(delivery, cast("Any", subs), ledger=ledger)
    calls = 0

    async def unavailable(
        _self: BilibiliDynamicOutboundSender, _item: dict[str, Any], _id: str
    ) -> OutboundMessage:
        nonlocal calls
        calls += 1
        raise TimeoutError

    monkeypatch.setattr(
        BilibiliDynamicOutboundSender, "_prepare_frozen_images", unavailable
    )
    item = _item()
    key = item["id_str"]
    targets = BiliPushTargets([TARGET], [], [], [])
    await sender.send(item, int(clock.now), 123, targets)
    rounds = ledger.round_count(key)
    for _ in range(8):
        ledger.recover()
        await sender.send(item, int(clock.now), 123, targets, resume=True)
    assert calls == len(("first", "retry-1", "retry-2", "retry-3"))
    assert ledger.attempts(key, TARGET, "image") == calls
    assert ledger.round_count(key) == rounds
    assert ledger.state_counts(key) == {"success": 2, "failed": 1}


@pytest.mark.asyncio
async def test_image_expansion_is_transactional(
    tmp_path: Path, clock: SimpleNamespace
) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    item = _item()
    key = item["id_str"]
    ledger.prepare(item, int(clock.now), 123, BiliPushTargets([TARGET], [], [], []), ())
    results = await asyncio.gather(
        *(asyncio.to_thread(ledger.image_units, key, TARGET, 2) for _ in range(2))
    )
    assert results.count(True) == 1
    assert ledger.state_counts(key) == {"pending": 4}


def test_permanent_preparation_failure_preserves_uncertain_receipt(
    tmp_path: Path,
    clock: SimpleNamespace,
) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    item = _item()
    key = item["id_str"]
    ledger.prepare(item, int(clock.now), 123, BiliPushTargets([TARGET], [], [], []), ())
    assert ledger.claim(key, TARGET, "image")
    ledger.recover()
    ledger.fail_media(
        key,
        TARGET,
        SendResult(
            delivered=False,
            error_code="frozen_media_unavailable",
            failure_kind=DeliveryFailureKind.PERMANENT,
        ),
    )
    assert ledger.state_counts(key) == {"pending": 2, "uncertain": 1}
