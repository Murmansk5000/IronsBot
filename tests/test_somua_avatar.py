from __future__ import annotations

import asyncio
import struct
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.extensions.somua_avatar import (
    SomuaAvatarParts,
    SomuaAvatarRequest,
    SomuaAvatarUnavailable,
)
from ironsbot.services.seer.observation_cache import ObservationCache
from ironsbot.services.seer.player_shortcut_contracts import PlayerShortcutDependencies
from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.query_work import QueryWorkResult
from ironsbot.services.seer.render_cache import RenderCacheEntry
from ironsbot.services.seer.render_coordinator import RenderCoordinator
from ironsbot.services.seer.somua_avatar import SomuaAvatarImages
from ironsbot.services.seer.somua_detail import (
    cached_detail_with_avatar,
    fetch_somua_detail_reply,
)
from ironsbot.services.seer.somua_models import SomuaParts

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

PLAYER = 700001
SEQUENCE = 111
IMAGE = b"synthetic image"
PARTS = SomuaParts(*range(9))


class MemoryCache:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], bytes] = {}
        self.writes = 0

    def entry(self, category: str, content_key: str) -> RenderCacheEntry:
        key = (category, content_key)

        def put(image: bytes) -> None:
            self.writes += 1
            self.values[key] = image

        return RenderCacheEntry(lambda: self.values.get(key), put)


class Provider:
    def __init__(self) -> None:
        self.resource_version = "resources-1"
        self.renderer_fingerprint = "renderer-1"
        self.degraded = False
        self.notice = ""
        self.render = AsyncMock(return_value=IMAGE)
        self.requests: list[SomuaAvatarRequest] = []
        self.closed = 0
        self.error: Exception | None = None

    @asynccontextmanager
    async def prepare(self, request: SomuaAvatarRequest) -> AsyncIterator[Provider]:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        try:
            yield self
        finally:
            self.closed += 1


def images(
    provider: Provider | None = None, *, timeout: float = 1
) -> tuple[SomuaAvatarImages, MemoryCache]:
    cache = MemoryCache()
    coordinator = RenderCoordinator(cast("Any", AsyncMock()), timeout)
    return SomuaAvatarImages(coordinator, cache, provider), cache


def reply() -> QueryReply:
    return QueryReply(
        leading_text="header",
        text="detail",
        fetched_at=123.0,
        query_work=QueryWorkResult(
            scope="foreground", successful_units=frozenset({"u"})
        ),
    )


def wire() -> bytes:
    head = struct.pack(
        "!I32s6I6I3I4I9I",
        SEQUENCE,
        b"Demo",
        *range(6),
        *range(6),
        *range(3),
        *range(4),
        *range(9),
    )
    parent = struct.pack("!32sI9I16sI", b"Parent", 2, *range(9), b"Owner", 10)
    return head + parent + parent + struct.pack("!IBI", 4, 1, PLAYER)


@pytest.mark.asyncio
async def test_no_provider_returns_original_reply() -> None:
    service, cache = images()
    original = reply()
    assert await service.attach(PARTS, original) is original
    assert cache.writes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("notice_fails", [False, True])
async def test_image_failure_uses_reporter_without_losing_text(
    *, notice_fails: bool
) -> None:
    provider = Provider()
    provider.render.side_effect = RuntimeError("failed renderer")
    service, cache = images(provider)
    report = AsyncMock(side_effect=RuntimeError("notice") if notice_fails else None)
    service.report_failure = report
    result = await service.attach(PARTS, reply())
    report.assert_awaited_once()
    assert result.text == "detail" and result.image_error and not result.complete
    assert cache.writes == 0 and provider.closed == 1


@pytest.mark.asyncio
async def test_expected_resource_unavailable_is_not_admin_error() -> None:
    provider = Provider()
    provider.error = SomuaAvatarUnavailable("preparing", "Preparing")
    service, _ = images(provider)
    report = AsyncMock()
    service.report_failure = report
    result = await service.attach(PARTS, reply())
    assert result.text == "detail" and result.image_error
    report.assert_not_awaited()


def test_duplicate_provider_is_rejected() -> None:
    service, _ = images()
    first = Provider()
    service.register_provider(first)
    with pytest.raises(ValueError, match="already registered"):
        service.register_provider(Provider())
    assert service.provider is first


@pytest.mark.parametrize("bad", [-1, 2**32, True, 1.5, "1"])
def test_parts_reject_invalid_values(bad: object) -> None:
    with pytest.raises(ValueError):
        SomuaAvatarParts(bad, *range(1, 9))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes", [{"pose": "other"}, {"time_seconds": 1}, {"width": 767}, {"height": 767}]
)
def test_request_rejects_unsupported_specification(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        SomuaAvatarRequest(SomuaAvatarParts(*range(9)), **changes)


@pytest.mark.asyncio
async def test_live_and_cached_detail_keep_observation_and_query_work() -> None:
    provider = Provider()
    service, cache = images(provider)
    observations = ObservationCache()
    deps = PlayerShortcutDependencies(
        cast("Any", None),
        cast("Any", None),
        1,
        3,
        1,
        observations,
        300,
        somua_avatar=service,
    )
    game = SimpleNamespace(send_and_wait=AsyncMock(return_value=(None, wire())))
    live = await fetch_somua_detail_reply(
        deps, game, player_id=PLAYER, sequence=SEQUENCE, anchor_only=False
    )
    cached = await fetch_somua_detail_reply(
        deps, game, player_id=PLAYER, sequence=SEQUENCE, anchor_only=True
    )
    direct = await cached_detail_with_avatar(
        observations, 300, PLAYER, SEQUENCE, avatar=service
    )
    game.send_and_wait.assert_awaited_once_with(45969, PLAYER, SEQUENCE)
    assert direct == cached
    assert live.image == cached.image == IMAGE
    assert live.text == cached.text and live.fetched_at == cached.fetched_at
    assert live.complete and cached.complete
    assert live.query_work is not None and cached.query_work is not None
    assert live.query_work.successful_units == frozenset({f"somua_detail:{SEQUENCE}"})
    assert cached.query_work.cached_units == frozenset({f"somua_detail:{SEQUENCE}"})
    assert not cached.query_work.billable_units
    assert provider.render.await_count == 1 and cache.writes == 1
    assert provider.requests[0].parts == SomuaAvatarParts(*range(9))
    assert provider.closed == len(provider.requests)


@pytest.mark.parametrize("failure", ["unavailable", "failed", "empty"])
@pytest.mark.asyncio
async def test_failure_preserves_reply_without_cache_write(failure: str) -> None:
    provider = Provider()
    if failure == "unavailable":
        provider.error = SomuaAvatarUnavailable("missing", "safe notice")
    elif failure == "failed":
        provider.render.side_effect = RuntimeError("secret internal detail")
    else:
        provider.render.return_value = b""
    service, cache = images(provider)
    original = reply()
    result = await service.attach(PARTS, original)
    assert result == replace(
        original, complete=False, image_error="苏摩图片暂不可用，已保留文字详情。"
    )
    assert cache.writes == 0 and not cache.values
    assert provider.closed == (0 if failure == "unavailable" else 1)


@pytest.mark.asyncio
async def test_degraded_cache_hit_keeps_notice_and_does_not_write() -> None:
    provider = Provider()
    service, cache = images(provider)
    assert (await service.attach(PARTS, reply())).image == IMAGE
    provider.degraded = True
    provider.notice = "older resources"
    result = await service.attach(PARTS, reply())
    assert result.image == IMAGE and result.text == "detail\nolder resources"
    assert not result.complete
    assert cache.writes == 1 and provider.render.await_count == 1


@pytest.mark.asyncio
async def test_cache_isolated_by_parts_resource_and_renderer() -> None:
    provider = Provider()
    service, cache = images(provider)
    await service.attach(PARTS, reply())
    await service.attach(PARTS, reply())
    await service.attach(replace(PARTS, body=99), reply())
    provider.resource_version = "resources-2"
    await service.attach(PARTS, reply())
    provider.renderer_fingerprint = "renderer-2"
    await service.attach(PARTS, reply())
    expected_entries = 4
    assert cache.writes == provider.render.await_count == expected_entries
    assert len(cache.values) == expected_entries


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.asyncio
async def test_timeout_or_cancellation_closes_lease_without_late_write(
    *, cancel: bool
) -> None:
    provider = Provider()
    entered = asyncio.Event()

    async def blocked() -> bytes:
        entered.set()
        await asyncio.Event().wait()
        return IMAGE

    provider.render.side_effect = blocked
    service, cache = images(provider, timeout=0.05 if not cancel else 1)
    task = asyncio.create_task(service.attach(PARTS, reply()))
    await entered.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert not (await task).complete
    await asyncio.sleep(0)
    assert provider.closed == 1 and cache.writes == 0


@pytest.mark.asyncio
async def test_native_and_avatar_backends_share_queue() -> None:
    provider = Provider()
    service, _ = images(provider)
    entered = asyncio.Event()
    release = asyncio.Event()
    native_entered = asyncio.Event()

    async def external() -> bytes:
        entered.set()
        await release.wait()
        return IMAGE

    async def native(*_args: Any, **_kwargs: Any) -> bytes:
        native_entered.set()
        return IMAGE

    provider.render.side_effect = external
    service.coordinator.renderer = cast("Any", native)
    avatar_task = asyncio.create_task(service.attach(PARTS, reply()))
    await entered.wait()
    native_task = asyncio.create_task(
        service.coordinator.render(cast("Any", ""), "native", {})
    )
    await asyncio.sleep(0)
    assert not native_entered.is_set()
    release.set()
    assert (await avatar_task).image == IMAGE
    assert await native_task == IMAGE and native_entered.is_set()
