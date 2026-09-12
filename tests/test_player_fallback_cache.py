import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import Mock

import pytest

from ironsbot.config.models.seer import SeerConfig
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.services.seer.player_query_cache import PlayerQueryCache
from ironsbot.services.seer.player_service import PlayerService
from ironsbot.services.seer.player_service_models import (
    PendingPlayerQuery,
    PlayerBaseSnapshot,
    PlayerQueryResult,
)

AT = 1_800_000_000.0
PLAYER = 123456


def pending(stamp: float | None = AT) -> PendingPlayerQuery:
    return PendingPlayerQuery(
        PLAYER,
        None,
        None,
        "cached",
        cast("Any", None),
        base_snapshot=PlayerBaseSnapshot(PLAYER, None, None, None, "", stamp),
    )


@pytest.fixture
def clocks(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    values = [AT, 100.0]
    monkeypatch.setattr(
        "ironsbot.services.seer.player_query_cache.now",
        lambda: datetime.fromtimestamp(values[0], tz=timezone.utc),
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_query_cache.monotonic", lambda: values[1]
    )
    return values


@pytest.mark.parametrize("stamp", [None, AT - 300, AT + 1, float("inf"), float("nan")])
@pytest.mark.usefixtures("clocks")
def test_base_cache_requires_fresh_observation(
    stamp: float | None,
) -> None:
    cache = PlayerQueryCache(300)
    cache.put(pending(stamp))
    assert cache.result(PLAYER, offer_binding=False) is None


@pytest.mark.usefixtures("clocks")
def test_missing_or_wrong_snapshot_not_admitted() -> None:
    cache = PlayerQueryCache(300)
    cache.put(replace(pending(), base_snapshot=None))
    assert cache.result(PLAYER, offer_binding=False) is None
    cache.put(replace(pending(), player_id=PLAYER + 1))
    assert cache.result(PLAYER + 1, offer_binding=False) is None


def test_reinsertion_retains_source_age_and_cached_quota(clocks: list[float]) -> None:
    cache = PlayerQueryCache(300)
    original = pending(AT - 250)
    cache.put(original)
    result = cache.result(PLAYER, offer_binding=True)
    assert result is not None and result.offer_binding
    assert result.pending is not None and result.pending.quota_recorded
    assert not original.quota_recorded
    clocks[0] += 49
    clocks[1] += 49
    cache.put(original)
    assert cache.result(PLAYER, offer_binding=False) is not None
    clocks[0] += 1
    clocks[1] += 1
    assert cache.result(PLAYER, offer_binding=False) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("elapsed,expired", [(10, False), (300, True)])
async def test_live_failure_checks_cache_at_return_time(
    clocks: list[float],
    monkeypatch: pytest.MonkeyPatch,
    elapsed: float,
    *,
    expired: bool,
) -> None:
    bindings = Mock()
    bindings.get.return_value.choice_completed = True
    service = PlayerService(
        SeerConfig(),
        cast("Any", Mock()),
        bindings,
        cast("Any", Mock()),
        cast("Any", Mock()),
    )
    service._query_cache.put(pending())
    started, release = asyncio.Event(), asyncio.Event()

    async def fail(*_args: object, **_kwargs: object) -> PlayerQueryResult:
        started.set()
        await release.wait()
        return PlayerQueryResult(message="live unavailable")

    monkeypatch.setattr(service, "_query", fail)
    task = asyncio.create_task(
        service.query(PLAYER, actor=ActorRef(Platform.ONEBOT, "100"), explicit=True)
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        clocks[0] += elapsed
        clocks[1] += elapsed
        release.set()
        result = await task
        if expired:
            assert result.pending is None and result.message == "live unavailable"
        else:
            assert (
                result.pending is not None and result.pending.player_message == "cached"
            )
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
