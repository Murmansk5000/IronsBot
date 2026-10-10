# ruff: noqa: PLR2004
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.config.models.seer import RankQueryConfig, SeerConfig
from ironsbot.core.time import TZ_CN, ObservationTime, now
from ironsbot.services.seer.observation_cache import ObservationCache
from ironsbot.services.seer.player_detail_service import PlayerDetailService
from ironsbot.services.seer.player_service_models import PlayerBaseSnapshot
from ironsbot.services.seer.player_shortcut_contracts import (
    PlayerShortcutCommand,
    PlayerShortcutDependencies,
)
from ironsbot.services.seer.player_shortcut_queries import fetch_player_shortcut_reply
from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.rank import RankService
from ironsbot.services.seer.rank_models import PlayerRankSummary, RankLookupResult
from ironsbot.services.seer.sequ_extra import (
    PEAK_PARAMS_BY_MODE,
    UnityPartOneInfo,
    fetch_unity_peak_partial,
)

PLAYER = 700001
TTL = 300


@pytest.mark.asyncio
async def test_observation_expiration_does_not_extend_on_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stamp = [1000.0]
    monkeypatch.setattr(
        "ironsbot.services.seer.observation_cache.clock.now",
        lambda: datetime.fromtimestamp(stamp[0], TZ_CN),
    )
    cache = ObservationCache()
    fetch = AsyncMock(return_value={"value": 12})
    first = ObservationTime()
    await cache.observe("packet", fetch, ttl=TTL, observation=first)
    stamp[0] += TTL - 1
    second = ObservationTime()
    value = await cache.observe("packet", fetch, ttl=TTL, observation=second)
    value["value"] = 999
    assert second.fetched_at == first.fetched_at
    assert fetch.await_count == 1
    stamp[0] += 1
    await cache.observe("packet", fetch, ttl=TTL, observation=ObservationTime())
    assert fetch.await_count == 2


@pytest.mark.asyncio
async def test_shared_observation_survives_one_waiter_cancelling() -> None:
    cache = ObservationCache(TaskOwner().create)
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def fetch() -> int:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return 42

    async def read() -> int:
        return await cache.observe(
            "packet", fetch, ttl=TTL, observation=ObservationTime()
        )

    first = asyncio.create_task(read())
    await started.wait()
    second = asyncio.create_task(read())
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert await second == 42
    assert calls == 1
    assert not cache._pending


@pytest.mark.asyncio
async def test_failed_observation_is_retried_without_losing_success() -> None:
    cache = ObservationCache()
    good = AsyncMock(return_value=9)
    bad = AsyncMock(side_effect=[TimeoutError(), 12])
    await cache.observe("good", good, ttl=TTL, observation=ObservationTime())
    with pytest.raises(TimeoutError):
        await cache.observe("bad", bad, ttl=TTL, observation=ObservationTime())
    await cache.observe("good", good, ttl=TTL, observation=ObservationTime())
    assert await cache.observe("bad", bad, ttl=TTL, observation=ObservationTime()) == 12
    assert good.await_count == 1
    assert bad.await_count == 2


def rank_service() -> RankService:
    return RankService(
        RankQueryConfig(),
        cast("Any", SimpleNamespace()),
        lambda: None,
        lambda: None,
        AsyncMock(),
        spawn=TaskOwner().create,
    )


@pytest.mark.asyncio
async def test_rank_success_reuse_score_cycle_and_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = rank_service()
    calls: list[dict[str, Any]] = []

    async def lookup(_self: Any, _game: Any, **kw: Any) -> RankLookupResult:
        calls.append(kw)
        result = RankLookupResult(
            "rank",
            "score",
            rank=3,
            score=kw.get("target_score") or 12,
            queried=True,
            fetched_at=now().timestamp(),
        )
        result.cost.online_page_fetches = 1
        return result

    monkeypatch.setattr(RankService, "_find_rank_uncached", lookup)
    kwargs: dict[str, Any] = {
        "user_id": PLAYER,
        "title": "rank",
        "score_name": "score",
        "key": 1,
        "sub_key": 7,
    }
    first = await service.find_rank(cast("Any", None), **kwargs)
    second = await service.find_rank(cast("Any", None), **kwargs)
    assert len(calls) == 1
    assert second.fetched_at == first.fetched_at
    assert second.failure is None and second.fallback_cached_at is None
    assert second.cost.online_page_fetches == 0
    await service.find_rank(cast("Any", None), **kwargs, target_score=13)
    assert len(calls) == 2
    kwargs["sub_key"] = 8
    await service.find_rank(cast("Any", None), **kwargs)
    assert len(calls) == 3
    service._confirmed.save((PLAYER, 1, 8), first, now().timestamp() - 601)
    # An older observation cannot overwrite newer evidence.
    service._confirmed.discard((PLAYER, 1, 8))
    service._confirmed.save((PLAYER, 1, 8), first, now().timestamp() - 601)
    await service.find_rank(cast("Any", None), **kwargs)
    assert len(calls) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "restricted", "undated", "fallback"])
async def test_rank_failed_or_unverified_result_not_reused(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    calls = 0

    async def lookup(_self: Any, _game: Any, **_kw: Any) -> RankLookupResult:
        nonlocal calls
        calls += 1
        result = RankLookupResult(
            "rank", "score", queried=True, fetched_at=now().timestamp()
        )
        if failure == "timeout":
            result.failure = "查询超时"
        elif failure == "restricted":
            result.cost.restricted_miss = True
        elif failure == "undated":
            result.fetched_at = None
        else:
            result.fallback_cached_at = result.fetched_at
        return result

    monkeypatch.setattr(RankService, "_find_rank_uncached", lookup)
    service = rank_service()
    for _ in range(2):
        await service.find_rank(
            cast("Any", None),
            user_id=PLAYER,
            title="rank",
            score_name="score",
            key=1,
            sub_key=0,
        )
    assert calls == 2


@pytest.mark.asyncio
async def test_peak_retries_only_failed_mode_and_invalidates_cycle() -> None:
    cache = ObservationCache()
    counts: Counter[int] = Counter()
    failed_param = PEAK_PARAMS_BY_MODE[1][1][0]

    class Game:
        async def send_and_wait(self, _cmd: int, _player: int, param: int) -> Any:
            counts[param] += 1
            if param == failed_param and counts[param] == 1:
                raise TimeoutError
            return None, SimpleNamespace(value=1)

    game = Game()
    first = await fetch_unity_peak_partial(
        game,
        PLAYER,
        timeout_seconds=1,
        observations=cache,
        cycles=(7, 8),
    )
    assert first.mode_errors
    second = await fetch_unity_peak_partial(
        game,
        PLAYER,
        timeout_seconds=1,
        observations=cache,
        cycles=(7, 8),
    )
    assert not second.mode_errors
    assert second.fetched_at == first.fetched_at
    assert counts[PEAK_PARAMS_BY_MODE[0][1][0]] == 1
    assert counts[failed_param] == 2
    await fetch_unity_peak_partial(
        game,
        PLAYER,
        timeout_seconds=1,
        observations=cache,
        cycles=(9, 8),
    )
    assert counts[PEAK_PARAMS_BY_MODE[0][1][0]] == 2
    assert counts[PEAK_PARAMS_BY_MODE[3][1][0]] == 1


@pytest.mark.asyncio
async def test_partial_collection_reuses_successful_packets_and_seven_ranks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = rank_service()
    counts: Counter[int] = Counter()
    stamp = now().timestamp()

    async def lookup(_self: Any, _game: Any, **kw: Any) -> RankLookupResult:
        key = kw["key"]
        counts[key] += 1
        result = RankLookupResult(
            "rank",
            "score",
            rank=key,
            score=100,
            queried=True,
            fetched_at=stamp,
        )
        result.cost.online_page_fetches = 1
        if key == 3 and counts[key] == 1:
            result.rank = None
            result.failure = "榜单在查询期间发生变化"
        return result

    monkeypatch.setattr(RankService, "_find_rank_uncached", lookup)
    fields = (
        "book",
        "achieve",
        "pet_kind",
        "skin",
        "countermark",
        "outfit_suit",
        "outfit_part",
        "mount",
    )

    class Rank:
        async def fetch_player_summary(self, game: Any, player: int, **_kw: Any) -> Any:
            results = await asyncio.gather(
                *(
                    service.find_rank(
                        game,
                        user_id=player,
                        title=name,
                        score_name="score",
                        key=index,
                        sub_key=0,
                    )
                    for index, name in enumerate(fields, 1)
                )
            )
            return PlayerRankSummary.from_results(
                dict(zip(fields, results, strict=True))
            )

    unity = AsyncMock(return_value=UnityPartOneInfo(pet_kind_num=100))
    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_part_one",
        unity,
    )
    game = SimpleNamespace(
        get_user_info=AsyncMock(return_value=SimpleNamespace(nick="player")),
        get_more_user_info=AsyncMock(
            return_value=SimpleNamespace(total_achieve=100, pet_all_num=200)
        ),
    )
    deps = PlayerShortcutDependencies(
        rank=cast("Any", Rank()),
        local_rank=cast("Any", SimpleNamespace(config=SimpleNamespace(enabled=False))),
        timeout_seconds=2,
        detail_timeout_seconds=3,
        rank_timeout_seconds=2,
        observations=ObservationCache(TaskOwner().create),
    )
    command = PlayerShortcutCommand(kind="collection", player_id=PLAYER)
    first = await fetch_player_shortcut_reply(
        deps, game, command=command, player_id=PLAYER
    )
    assert not first.complete
    second = await fetch_player_shortcut_reply(
        deps, game, command=command, player_id=PLAYER
    )
    assert second.complete
    assert second.fetched_at == first.fetched_at
    assert counts == Counter({1: 1, 2: 1, 3: 2, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1})
    game.get_user_info.assert_awaited_once()
    game.get_more_user_info.assert_awaited_once()
    unity.assert_awaited_once()
    assert "上次记录" not in second.text
    third = await fetch_player_shortcut_reply(
        deps, game, command=command, player_id=PLAYER
    )
    assert third.rank_lookup_is_lightweight
    assert not third.rank_lookup_should_charge_quota


@pytest.mark.asyncio
async def test_complete_miss_is_reused_only_for_the_confirmed_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def lookup(_self: Any, _game: Any, **kw: Any) -> RankLookupResult:
        nonlocal calls
        calls += 1
        return RankLookupResult(
            "rank",
            "score",
            queried=True,
            searched_limit=kw["search_limit"],
            fetched_at=now().timestamp(),
        )

    monkeypatch.setattr(RankService, "_find_rank_uncached", lookup)
    service = rank_service()
    for limit in (100, 100, 200):
        await service.find_rank(
            cast("Any", None),
            user_id=PLAYER,
            title="rank",
            score_name="score",
            key=1,
            sub_key=0,
            search_limit=limit,
        )
    assert calls == 2


@pytest.mark.asyncio
async def test_new_base_score_invalidates_complete_collection_reply() -> None:
    stamp = now().timestamp()
    service = PlayerDetailService(
        SeerConfig(),
        rank_service(),
        cast("Any", object()),
        TaskOwner().create,
    )

    def snapshot(score: int, fetched_at: float) -> PlayerBaseSnapshot:
        return PlayerBaseSnapshot(
            PLAYER,
            SimpleNamespace(nick="player"),
            SimpleNamespace(total_achieve=score, pet_all_num=200),
            None,
            "",
            fetched_at,
        )

    old = snapshot(100, stamp - 10)
    service.remember_snapshot(old)
    service._store_reply(
        PLAYER,
        "collection",
        QueryReply(text="old", fetched_at=old.fetched_at),
    )
    assert await service.cached_or_inflight_reply(PLAYER, "collection") is not None
    assert (
        await service.cached_or_inflight_reply(
            PLAYER,
            "collection",
            snapshot(101, stamp),
        )
        is None
    )
    cached = service._observations.get((PLAYER, "more_info"), TTL)
    assert cached is not None and cached.value.total_achieve == 101
