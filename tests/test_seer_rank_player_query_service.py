from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.services.seer import rank_player_query
from ironsbot.services.seer.local_rank import LocalRankService
from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.rank import RankService
from ironsbot.services.seer.rank_list_models import (
    GLOBAL_RANKS,
    GlobalRankSpec,
    RankPlayerCommand,
)
from ironsbot.services.seer.rank_models import RankLookupResult

PLAYER_ID = 123456
ACHIEVEMENT_SCORE = 5000
CURRENT_PEAK_SCORE = 300033


@pytest.mark.asyncio
async def test_pet_profile_and_rank_scores_are_labelled_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_score = 4894
    board_score = 4646
    monkeypatch.setattr(
        rank_player_query,
        "fetch_unity_part_one",
        AsyncMock(return_value=SimpleNamespace(pet_kind_num=profile_score)),
    )
    rank = build_rank_stub(AsyncMock())
    monkeypatch.setattr(
        rank,
        "find_pet_kind_rank",
        AsyncMock(
            return_value=RankLookupResult(
                title="精灵图鉴",
                score_name="项",
                rank=2,
                score=board_score,
                observed_score=board_score,
                queried=True,
            )
        ),
    )
    local_rank, upsert = build_local_rank_stub(enabled=True)
    message = await rank_player_query.fetch_rank_player_message(
        rank,
        local_rank,
        FakeGame(),
        command=RankPlayerCommand(rank_key="精灵图鉴", player_id=PLAYER_ID),
    )
    assert "个人接口：4894项｜榜单：4646项｜全服第2" in message
    assert upsert.await_args is not None
    assert (
        upsert.await_args.kwargs["current_metrics"]["pet_kind_count"]["value"]
        == profile_score
    )


class FakeGame:
    async def get_user_info(self, user_id: int) -> object:
        return SimpleNamespace(user_id=user_id, nick="测试玩家")

    async def get_more_user_info(self, user_id: int) -> object:
        return SimpleNamespace(user_id=user_id, total_achieve=5000)


def build_local_rank_stub(
    *,
    enabled: bool,
    summary: LocalRankSummary | None = None,
) -> tuple[LocalRankService, AsyncMock]:
    upsert = AsyncMock(return_value=summary or LocalRankSummary())
    service = cast(
        "LocalRankService",
        SimpleNamespace(
            config=SimpleNamespace(enabled=enabled),
            upsert_metrics=upsert,
        ),
    )
    return service, upsert


def build_rank_stub(
    find_rank: Any,
    *,
    spec: GlobalRankSpec | None = None,
) -> RankService:
    return cast(
        "RankService",
        SimpleNamespace(
            find_rank=find_rank,
            find_pet_kind_rank=AsyncMock(),
            get_spec=lambda rank_key: spec or GLOBAL_RANKS[rank_key],
            spec_needs_sub_key=lambda _spec: False,
        ),
    )


@pytest.mark.asyncio
async def test_rank_player_query_fetches_only_achievement_source() -> None:
    captured: dict[str, Any] = {}

    async def fake_find_rank(_game: object, **kwargs: Any) -> RankLookupResult:
        captured.update(kwargs)
        return RankLookupResult(
            title="成就点数",
            score_name="点",
            rank=42,
            score=ACHIEVEMENT_SCORE,
            searched_limit=50000,
            queried=True,
        )

    rank = build_rank_stub(fake_find_rank)
    local_rank, _ = build_local_rank_stub(enabled=False)

    message = await rank_player_query.fetch_rank_player_message(
        rank,
        local_rank,
        FakeGame(),
        command=RankPlayerCommand(rank_key="成就点数", player_id=PLAYER_ID),
    )

    assert captured["user_id"] == PLAYER_ID
    assert captured["target_score"] == ACHIEVEMENT_SCORE
    assert message == (
        "📊【成就点数榜玩家查询】\n"
        "米米号：123456（测试玩家）\n"
        "成就点数：5000点｜全服第42"
    )


@pytest.mark.asyncio
async def test_rank_player_query_writes_only_current_metric() -> None:
    async def fake_find_rank(_game: object, **_kwargs: Any) -> RankLookupResult:
        return RankLookupResult(
            title="成就点数",
            score_name="点",
            rank=42,
            score=ACHIEVEMENT_SCORE,
            searched_limit=50000,
            queried=True,
        )

    rank = build_rank_stub(fake_find_rank)
    local_rank, upsert = build_local_rank_stub(
        enabled=True,
        summary=LocalRankSummary(sample_ranks={"achievement_score": "样本前10%"}),
    )

    message = await rank_player_query.fetch_rank_player_message(
        rank,
        local_rank,
        FakeGame(),
        command=RankPlayerCommand(rank_key="成就点数", player_id=PLAYER_ID),
    )

    assert upsert.await_args is not None
    captured = upsert.await_args.kwargs
    assert set(captured["current_metrics"]) == {"achievement_score"}
    assert "样本前10%" in message


@pytest.mark.asyncio
async def test_rank_player_query_uses_unknown_score_cache_lookup() -> None:
    captured: dict[str, Any] = {}

    async def fake_find_rank(_game: object, **kwargs: Any) -> RankLookupResult:
        captured.update(kwargs)
        return RankLookupResult(
            title="群星之巅",
            score_name="分",
            rank=3149,
            score=2465,
            searched_limit=2000,
            queried=True,
        )

    rank = build_rank_stub(fake_find_rank)
    local_rank, _ = build_local_rank_stub(enabled=False)

    message = await rank_player_query.fetch_rank_player_message(
        rank,
        local_rank,
        FakeGame(),
        command=RankPlayerCommand(rank_key="群星牌", player_id=PLAYER_ID),
    )

    assert captured["target_score"] is None
    assert "群星之巅：2465分｜全服第3149" in message


@pytest.mark.asyncio
async def test_peak_rank_player_query_retries_without_stale_forever_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int | None] = []

    async def fake_fetch_unity_peak(
        _game: object,
        _player_id: int,
    ) -> object:
        return SimpleNamespace(
            current_j_rank=4,
            current_j_star=0,
            current_j_all=124,
            current_k_rank=0,
            current_k_star=0,
            current_k_all=0,
            current_z_score=0,
            current_z_all=0,
        )

    async def fake_find_rank(_game: object, **kwargs: Any) -> RankLookupResult:
        target_score = kwargs.get("target_score")
        calls.append(target_score)
        if target_score is not None:
            return RankLookupResult(
                title="竞技段位",
                score_name="",
                score=int(target_score),
                searched_limit=50000,
                queried=True,
            )
        return RankLookupResult(
            title="竞技段位",
            score_name="",
            rank=9,
            score=CURRENT_PEAK_SCORE,
            searched_limit=2000,
            queried=True,
        )

    monkeypatch.setattr(rank_player_query, "fetch_unity_peak", fake_fetch_unity_peak)
    rank = build_rank_stub(
        fake_find_rank,
        spec=GlobalRankSpec(
            title="竞技段位榜",
            key=20,
            sub_key=20260717,
            unit="",
            peak_season_sub_key=True,
        ),
    )
    local_rank, upsert = build_local_rank_stub(enabled=True)

    message = await rank_player_query.fetch_rank_player_message(
        rank,
        local_rank,
        FakeGame(),
        command=RankPlayerCommand(rank_key="竞技段位", player_id=PLAYER_ID),
    )

    assert calls == [400000, None]
    assert "竞技段位：个人接口：圣皇0星｜榜单：王者33星｜全服第9" in message
    assert upsert.await_args is not None
    stored = upsert.await_args.kwargs
    assert stored["current_metrics"]["peak_standard"]["value"] == CURRENT_PEAK_SCORE
