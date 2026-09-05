# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.integrations.storage.seer_assets import (
    SeerAssetStore,
    SeerAssetStoreLimits,
)
from ironsbot.services.seer.images import ImageSourceError, ImageSourceStatusError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ironsbot.services.seer.images import SeerImageSource


SECOND_FETCH_COUNT = 2


class FakeImageSource:
    def __init__(
        self,
        *,
        result: bytes = b"asset",
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls = 0
        self.started = asyncio.Event()
        self.release: asyncio.Event | None = None

    async def fetch(
        self,
        _kind: str,
        _key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        del fallback
        self.calls += 1
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return self.result

    async def fetch_url(self, _url: str) -> bytes:
        return await self.fetch("url", _url)


def _store(
    source: FakeImageSource,
    directory: Path,
    *,
    source_identity_getter: Callable[[], str] | None = None,
) -> SeerAssetStore:
    return SeerAssetStore(
        cast("SeerImageSource", source),
        directory,
        SeerAssetStoreLimits(
            memory_max_size_bytes=1024,
            disk_max_size_bytes=1024 * 1024,
            max_network_concurrent=4,
            negative_ttl_seconds=300,
        ),
        source_identity_getter=source_identity_getter,
    )


@pytest.mark.asyncio
async def test_asset_store_coalesces_concurrent_requests(tmp_path: Path) -> None:
    source = FakeImageSource()
    source.release = asyncio.Event()
    store = _store(source, tmp_path)

    first = asyncio.create_task(store.fetch("pet_body", "1", fallback=False))
    await source.started.wait()
    second = asyncio.create_task(store.fetch("pet_body", "1", fallback=False))
    await asyncio.sleep(0)
    assert source.calls == 1

    source.release.set()

    assert await asyncio.gather(first, second) == [b"asset", b"asset"]
    assert source.calls == 1


@pytest.mark.asyncio
async def test_asset_store_reads_verified_asset_from_disk(tmp_path: Path) -> None:
    initial = FakeImageSource(result=b"persisted")
    assert await _store(initial, tmp_path).fetch("pet_head", "2") == b"persisted"

    restored = FakeImageSource(error=AssertionError("network should not run"))
    assert await _store(restored, tmp_path).fetch("pet_head", "2") == b"persisted"
    assert restored.calls == 0


@pytest.mark.asyncio
async def test_asset_store_does_not_reuse_a_prior_asset_revision(
    tmp_path: Path,
) -> None:
    assert await _store(
        FakeImageSource(result=b"old"),
        tmp_path,
        source_identity_getter=lambda: "assets@old",
    ).fetch("pet_head", "2") == b"old"

    refreshed = FakeImageSource(result=b"new")
    assert await _store(
        refreshed,
        tmp_path,
        source_identity_getter=lambda: "assets@new",
    ).fetch("pet_head", "2") == b"new"
    assert refreshed.calls == 1


@pytest.mark.asyncio
async def test_asset_store_refetches_corrupt_disk_asset(tmp_path: Path) -> None:
    assert await _store(FakeImageSource(result=b"first"), tmp_path).fetch(
        "pet_head", "3"
    ) == b"first"
    asset_path = await asyncio.to_thread(lambda: next(tmp_path.glob("*.bin")))
    await asyncio.to_thread(asset_path.write_bytes, b"corrupt")

    source = FakeImageSource(result=b"replacement")
    assert await _store(source, tmp_path).fetch("pet_head", "3") == b"replacement"
    assert source.calls == 1


@pytest.mark.asyncio
async def test_asset_store_only_negative_caches_missing_assets(tmp_path: Path) -> None:
    missing = FakeImageSource(error=ImageSourceStatusError(404, "Not Found"))
    store = _store(missing, tmp_path)

    with pytest.raises(ImageSourceStatusError):
        await store.fetch("item", "404", fallback=False)
    with pytest.raises(ImageSourceStatusError):
        await store.fetch("item", "404", fallback=False)
    assert missing.calls == 1

    transient = FakeImageSource(error=ImageSourceError("connection reset"))
    transient_store = _store(transient, tmp_path)
    with pytest.raises(ImageSourceError):
        await transient_store.fetch("item", "500", fallback=False)
    with pytest.raises(ImageSourceError):
        await transient_store.fetch("item", "500", fallback=False)
    assert transient.calls == SECOND_FETCH_COUNT
