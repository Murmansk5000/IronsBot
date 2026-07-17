from types import SimpleNamespace
from typing import Any

import pytest

from ironsbot.services.seer import rank_player_query
from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.rank_list_models import RankPlayerCommand
from ironsbot.services.seer.rank_models import RankLookupResult

PLAYER_ID = 123456
ACHIEVEMENT_SCORE = 5000
CURRENT_PEAK_SCORE = 300033


class FakeGame:
    async def get_user_info(self, user_id: int) -> object:
        return SimpleNamespace(user_id=user_id, nick="测试玩家")

    async def get_more_user_info(self, user_id: int) -> object:
        return SimpleNamespace(user_id=user_id, total_achieve=5000)


@pytest.mark.asyncio
async def test_rank_player_query_fetches_only_achievement_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    monkeypatch.setattr(rank_player_query, "find_rank", fake_find_rank)

    message = await rank_player_query.fetch_rank_player_message(
        FakeGame(),
        command=RankPlayerCommand(rank_key="成就点数", player_id=PLAYER_ID),
        local_rank_enabled=False,
    )

    assert captured["user_id"] == PLAYER_ID
    assert captured["target_score"] == ACHIEVEMENT_SCORE
    assert message == (
        "📊【成就点数榜玩家查询】\n"
        "米米号：123456（测试玩家）\n"
        "成就点数：5000点｜全服第42"
    )


@pytest.mark.asyncio
async def test_rank_player_query_writes_only_current_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_find_rank(_game: object, **_kwargs: Any) -> RankLookupResult:
        return RankLookupResult(
            title="成就点数",
            score_name="点",
            rank=42,
            score=ACHIEVEMENT_SCORE,
            searched_limit=50000,
            queried=True,
        )

    async def fake_upsert(**kwargs: Any) -> LocalRankSummary:
        captured.update(kwargs)
        return LocalRankSummary(sample_ranks={"achievement_score": "样本前10%"})

    monkeypatch.setattr(rank_player_query, "find_rank", fake_find_rank)
    monkeypatch.setattr(rank_player_query, "upsert_local_rank_metrics", fake_upsert)

    message = await rank_player_query.fetch_rank_player_message(
        FakeGame(),
        command=RankPlayerCommand(rank_key="成就点数", player_id=PLAYER_ID),
        local_rank_enabled=True,
    )

    assert set(captured["current_metrics"]) == {"achievement_score"}
    assert "样本前10%" in message


@pytest.mark.asyncio
async def test_rank_player_query_uses_unknown_score_cache_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    monkeypatch.setattr(rank_player_query, "find_rank", fake_find_rank)

    message = await rank_player_query.fetch_rank_player_message(
        FakeGame(),
        command=RankPlayerCommand(rank_key="群星牌", player_id=PLAYER_ID),
        local_rank_enabled=False,
    )

    assert captured["target_score"] is None
    assert "群星之巅：2465分｜全服第3149" in message


@pytest.mark.asyncio
async def test_peak_rank_player_query_retries_without_stale_forever_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int | None] = []
    stored: dict[str, Any] = {}

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

    async def fake_upsert(**kwargs: Any) -> LocalRankSummary:
        stored.update(kwargs)
        return LocalRankSummary()

    monkeypatch.setattr(rank_player_query, "fetch_unity_peak", fake_fetch_unity_peak)
    monkeypatch.setattr(rank_player_query, "find_rank", fake_find_rank)
    monkeypatch.setattr(rank_player_query, "upsert_local_rank_metrics", fake_upsert)
    monkeypatch.setattr(
        rank_player_query,
        "get_global_rank_spec",
        lambda _key: SimpleNamespace(
            key=20,
            sub_key=20260717,
            title="竞技段位榜",
            unit="",
            peak_season_sub_key=True,
        ),
    )

    message = await rank_player_query.fetch_rank_player_message(
        FakeGame(),
        command=RankPlayerCommand(rank_key="竞技段位", player_id=PLAYER_ID),
        local_rank_enabled=True,
    )

    assert calls == [400000, None]
    assert "竞技段位：王者33星｜全服第9" in message
    assert stored["current_metrics"]["peak_standard"]["value"] == CURRENT_PEAK_SCORE
