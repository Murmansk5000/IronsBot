import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.config.models.seer import PlayerRankLookupConfig
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.player_service_models import PlayerBaseSnapshot
from ironsbot.services.seer.player_shortcut_contracts import (
    PlayerShortcutCommand,
    PlayerShortcutDependencies,
)
from ironsbot.services.seer.player_shortcut_queries import (
    fetch_player_shortcut_reply,
)
from ironsbot.services.seer.rank_constants import (
    BOOK_RANK_KEY,
    STANDARD_PEAK_USER_RANK_KEY,
)
from ironsbot.services.seer.rank_models import (
    PeakSeasonRankSummary,
    PlayerRankSummary,
    RankLookupCost,
    RankLookupResult,
)
from ironsbot.services.seer.rank_player_scheduler import (
    current_player_rank_page_scheduler,
    run_player_rank_lookup_jobs,
)
from ironsbot.services.seer.rank_summary import (
    fetch_peak_season_rank_summary,
    fetch_player_rank_summary,
)
from ironsbot.services.seer.sequ_extra import (
    UnityPartOneInfo,
    UnityPeakFetchResult,
    UnityPeakInfo,
)

PLAYER_ID = 813_824_069
_TEST_STAGE_TIMEOUT_SECONDS = 0.01
_CACHED_AT = 1234567890


@pytest.mark.asyncio
async def test_season_database_failure_preserves_peak_base_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_peak_partial",
        AsyncMock(
            return_value=UnityPeakFetchResult(
                UnityPeakInfo(current_z_score=1421, current_z_all=10),
                frozenset(("standard", "wild", "expert")),
                fetched_at=1_800_000_000,
            )
        ),
    )
    rank = SimpleNamespace(
        current_peak_sub_key=Mock(
            side_effect=DataUnavailableError("巅峰赛季数据读取失败")
        ),
        fetch_peak_summary=AsyncMock(),
    )
    local = SimpleNamespace(
        config=SimpleNamespace(enabled=True), upsert_metrics=AsyncMock()
    )
    reply = await fetch_player_shortcut_reply(
        _dependencies(rank, local),
        SimpleNamespace(
            get_user_info=AsyncMock(return_value=SimpleNamespace(nick="tester"))
        ),
        command=PlayerShortcutCommand(kind="peak", player_id=PLAYER_ID),
        player_id=PLAYER_ID,
    )
    assert "1421" in reply.text
    assert "巅峰赛季数据读取失败" in reply.text
    assert "未上榜" not in reply.text
    assert not reply.complete
    assert all(result.failure for result in reply.rank_lookups)
    rank.fetch_peak_summary.assert_not_awaited()
    local.upsert_metrics.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["collection", "peak", "autocard"])
async def test_expired_detail_budget_does_not_start_more_queries(kind: Any) -> None:
    game = SimpleNamespace(
        get_user_info=AsyncMock(),
        get_more_user_info=AsyncMock(),
        send_and_wait=AsyncMock(),
    )
    rank = SimpleNamespace(
        fetch_player_summary=AsyncMock(),
        fetch_peak_summary=AsyncMock(),
        fetch_autocard_summary=AsyncMock(),
        current_peak_sub_key=lambda: 7,
    )
    local = SimpleNamespace(
        config=SimpleNamespace(enabled=True), upsert_metrics=AsyncMock()
    )
    reply = await fetch_player_shortcut_reply(
        _dependencies(rank, local, detail_timeout_seconds=0),
        game,
        command=PlayerShortcutCommand(kind=kind, player_id=PLAYER_ID),
        player_id=PLAYER_ID,
    )
    for query in (
        game.get_user_info,
        game.get_more_user_info,
        game.send_and_wait,
        rank.fetch_player_summary,
        rank.fetch_peak_summary,
        rank.fetch_autocard_summary,
        local.upsert_metrics,
    ):
        query.assert_not_awaited()
    assert reply.rank_lookups
    assert all(result.failure == "查询超时" for result in reply.rank_lookups)
    assert not reply.complete


def _dependencies(
    rank: Any,
    local_rank: Any,
    *,
    timeout_seconds: float = 30.0,
    detail_timeout_seconds: float = 90.0,
    rank_timeout_seconds: float = _TEST_STAGE_TIMEOUT_SECONDS,
) -> PlayerShortcutDependencies:
    return PlayerShortcutDependencies(
        rank=rank,
        local_rank=local_rank,
        timeout_seconds=timeout_seconds,
        detail_timeout_seconds=detail_timeout_seconds,
        rank_timeout_seconds=rank_timeout_seconds,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["collection", "peak"])
async def test_shortcut_summary_timeout_preserves_completed_boards(  # noqa: C901
    monkeypatch: pytest.MonkeyPatch,
    kind: Any,
) -> None:
    completed: list[RankLookupResult] = []
    page_drained = asyncio.Event()
    config = PlayerRankLookupConfig()

    async def find_rank(_game: object, **kwargs: Any) -> RankLookupResult:
        scheduler = current_player_rank_page_scheduler()
        assert scheduler is not None

        async def page() -> None:
            if kwargs.get("key") in {BOOK_RANK_KEY, STANDARD_PEAK_USER_RANK_KEY}:
                try:
                    await asyncio.Event().wait()
                finally:
                    page_drained.set()

        await scheduler.fetch_page(kwargs.get("title", "pet_kind"), page)
        result = RankLookupResult(
            title=kwargs.get("title", "精灵图鉴"),
            score_name=kwargs.get("score_name", "精灵"),
            rank=4,
            score=kwargs.get("target_score") or 1421,
            queried=True,
            fallback_cached_at=_CACHED_AT,
            cost=RankLookupCost(cache_page_hits=1),
        )
        completed.append(result)
        return result

    async def runner(jobs: Any) -> dict[str, RankLookupResult]:
        return await run_player_rank_lookup_jobs(jobs, config)

    class Rank:
        @staticmethod
        def current_peak_sub_key() -> int:
            return 7

        async def fetch_player_summary(
            self,
            game: object,
            player_id: int,
            **kwargs: Any,
        ) -> PlayerRankSummary:
            return await fetch_player_rank_summary(
                game,
                player_id,
                find_rank=find_rank,
                find_pet_kind_rank=find_rank,
                book_breakdown_limit=2000,
                run_lookup_jobs=runner,
                **kwargs,
            )

        async def fetch_peak_summary(
            self,
            game: object,
            player_id: int,
            **kwargs: Any,
        ) -> Any:
            return await fetch_peak_season_rank_summary(
                game,
                player_id,
                find_rank=find_rank,
                current_peak_sub_key=7,
                run_lookup_jobs=runner,
                **kwargs,
            )

    async def collection_base(*_args: Any) -> UnityPartOneInfo:
        return UnityPartOneInfo(pet_kind_num=1326, skin_num=79)

    async def peak_base(*_args: Any, **_kwargs: Any) -> UnityPeakFetchResult:
        return UnityPeakFetchResult(
            UnityPeakInfo(current_j_rank=3, current_k_rank=3, current_z_score=1421),
            frozenset({"standard", "wild", "expert"}),
        )

    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_part_one",
        collection_base,
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_peak_partial",
        peak_base,
    )
    local = _RecordingLocalRank()
    reply = await fetch_player_shortcut_reply(
        _dependencies(
            rank=cast("Any", Rank()),
            local_rank=cast("Any", local),
            rank_timeout_seconds=0.05,
        ),
        _Game(),
        command=PlayerShortcutCommand(kind=kind, player_id=PLAYER_ID),
        player_id=PLAYER_ID,
    )

    assert completed
    assert page_drained.is_set()
    assert current_player_rank_page_scheduler() is None
    assert reply.text.splitlines()[1].startswith("获取时间：")
    assert "全服第4" in reply.text or "赛季榜第4" in reply.text
    assert len(local.calls) == 1
    for result in completed:
        assert any(item is result for item in reply.rank_lookups)
        assert result.failure is None
        assert result.fallback_cached_at == _CACHED_AT
        assert result.cost.cache_page_hits == 1
    unfinished = [item for item in reply.rank_lookups if item.rank is None]
    assert len(unfinished) == 1
    assert unfinished[0].failure == "查询超时"
    assert not reply.complete


class _Game:
    async def get_user_info(self, player_id: int) -> SimpleNamespace:
        assert player_id == PLAYER_ID
        return SimpleNamespace(nick="decial")

    async def get_more_user_info(self, player_id: int) -> SimpleNamespace:
        assert player_id == PLAYER_ID
        return SimpleNamespace(total_achieve=5760, pet_all_num=1231)


class _Rank:
    async def fetch_player_summary(
        self,
        _game: object,
        player_id: int,
        **kwargs: Any,
    ) -> object:
        assert player_id == PLAYER_ID
        kwargs["progress"].current_title = "皮肤图鉴榜"
        await asyncio.Event().wait()
        raise AssertionError


class _LocalRank:
    config = SimpleNamespace(enabled=False)

    async def upsert_metrics(self, **_kwargs: object) -> LocalRankSummary:
        raise AssertionError


class _RecordingLocalRank:
    config = SimpleNamespace(enabled=True)

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def upsert_metrics(self, **kwargs: object) -> LocalRankSummary:
        self.calls.append(kwargs)
        return LocalRankSummary()


class _RankWithoutData:
    async def fetch_player_summary(
        self,
        _game: object,
        player_id: int,
        **_kwargs: object,
    ) -> PlayerRankSummary:
        assert player_id == PLAYER_ID
        return PlayerRankSummary.empty()


@pytest.mark.asyncio
async def test_collection_returns_partial_result_with_exact_timeout_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fetch_unity_part_one(
        _game: object,
        player_id: int,
    ) -> UnityPartOneInfo:
        assert player_id == PLAYER_ID
        return UnityPartOneInfo(
            achievement_num=372,
            pet_kind_num=1326,
            skin_num=79,
        )

    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_part_one",
        fetch_unity_part_one,
    )
    reply = await fetch_player_shortcut_reply(
        _dependencies(
            rank=cast("Any", _Rank()),
            local_rank=cast("Any", _LocalRank()),
            timeout_seconds=_TEST_STAGE_TIMEOUT_SECONDS,
        ),
        _Game(),
        command=PlayerShortcutCommand(kind="collection", player_id=PLAYER_ID),
        player_id=PLAYER_ID,
    )

    assert "📚【收集与排行】" in reply.text
    assert reply.text.splitlines()[1].startswith("获取时间：")
    assert f"米米号：{PLAYER_ID}（decial）" in reply.text
    assert "精灵数量：1231" in reply.text
    assert "皮肤图鉴：79｜全服排行失败：查询超时" in reply.text
    assert "❌ 米米号" not in reply.text


@pytest.mark.asyncio
async def test_successful_collection_shortcut_adds_player_to_local_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fetch_unity_part_one(
        _game: object,
        player_id: int,
    ) -> UnityPartOneInfo:
        assert player_id == PLAYER_ID
        return UnityPartOneInfo(
            achievement_num=372,
            pet_kind_num=1326,
            skin_num=79,
        )

    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_part_one",
        fetch_unity_part_one,
    )
    local_rank = _RecordingLocalRank()

    await fetch_player_shortcut_reply(
        _dependencies(
            rank=cast("Any", _RankWithoutData()),
            local_rank=cast("Any", local_rank),
        ),
        _Game(),
        command=PlayerShortcutCommand(kind="collection", player_id=PLAYER_ID),
        player_id=PLAYER_ID,
    )

    assert len(local_rank.calls) == 1
    call = local_rank.calls[0]
    assert call["player_id"] == PLAYER_ID
    assert call["nick"] == "decial"
    metrics = cast("dict[str, object]", call["current_metrics"])
    assert {"achievement_score", "achievement_count", "pet_total_count"} <= set(metrics)


@pytest.mark.asyncio
async def test_collection_menu_snapshot_reuses_confirmed_nick_and_more_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Game:
        async def get_user_info(self, _player_id: int) -> SimpleNamespace:
            raise AssertionError

        async def get_more_user_info(self, _player_id: int) -> SimpleNamespace:
            raise AssertionError

    async def fetch_unity_part_one(
        _game: object,
        player_id: int,
    ) -> UnityPartOneInfo:
        assert player_id == PLAYER_ID
        return UnityPartOneInfo(achievement_num=372, pet_kind_num=1326, skin_num=79)

    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_part_one",
        fetch_unity_part_one,
    )
    snapshot = PlayerBaseSnapshot(
        player_id=PLAYER_ID,
        user_info=SimpleNamespace(nick="already fetched"),
        more_info=SimpleNamespace(total_achieve=5760, pet_all_num=1231),
        online_info=None,
        team_name="snapshot team",
        fetched_at=1_700_000_000,
    )

    reply = await fetch_player_shortcut_reply(
        _dependencies(
            rank=cast("Any", _RankWithoutData()),
            local_rank=cast("Any", _LocalRank()),
        ),
        Game(),
        command=PlayerShortcutCommand(
            kind="collection",
            player_id=PLAYER_ID,
            base_snapshot=snapshot,
        ),
        player_id=PLAYER_ID,
    )

    assert f"米米号：{PLAYER_ID}（already fetched）" in reply.text
    assert "精灵数量：1231" in reply.text


@pytest.mark.asyncio
async def test_direct_collection_inlines_nickname_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Game:
        async def get_user_info(self, _player_id: int) -> SimpleNamespace:
            await asyncio.Event().wait()
            raise AssertionError

        async def get_more_user_info(self, _player_id: int) -> SimpleNamespace:
            return SimpleNamespace(total_achieve=5760, pet_all_num=1231)

    async def fetch_unity_part_one(
        _game: object,
        player_id: int,
    ) -> UnityPartOneInfo:
        assert player_id == PLAYER_ID
        return UnityPartOneInfo(achievement_num=372, pet_kind_num=1326, skin_num=79)

    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_part_one",
        fetch_unity_part_one,
    )
    reply = await fetch_player_shortcut_reply(
        _dependencies(
            rank=cast("Any", _RankWithoutData()),
            local_rank=cast("Any", _LocalRank()),
            timeout_seconds=_TEST_STAGE_TIMEOUT_SECONDS,
        ),
        Game(),
        command=PlayerShortcutCommand(kind="collection", player_id=PLAYER_ID),
        player_id=PLAYER_ID,
    )

    assert f"米米号：{PLAYER_ID}（昵称暂未获取：查询超时）" in reply.text
    assert "玩家昵称失败" not in reply.text
    assert not reply.complete


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "outcome"),
    [
        (kind, outcome)
        for kind in ("collection", "peak", "autocard")
        for outcome in ("ok", "miss", "nick", "base", "rank", "restricted", "sample")
        if (kind, outcome) != ("autocard", "base")
    ],
)
async def test_detail_completeness_uses_all_requested_stages(
    monkeypatch: pytest.MonkeyPatch,
    kind: Any,
    outcome: str,
) -> None:
    result = RankLookupResult(
        title="rank",
        score_name="score",
        queried=True,
        rank=None if outcome == "miss" else 4,
        score=None if outcome == "miss" else 1421,
        searched_limit=2000,
        failure="unavailable" if outcome == "rank" else None,
        cost=RankLookupCost(restricted_miss=outcome == "restricted"),
    )
    rank = SimpleNamespace(
        fetch_player_summary=AsyncMock(
            return_value=PlayerRankSummary.from_results(
                dict.fromkeys(
                    (
                        "book",
                        "achieve",
                        "pet_kind",
                        "skin",
                        "countermark",
                        "outfit_suit",
                        "outfit_part",
                        "mount",
                    ),
                    result,
                )
            )
        ),
        fetch_peak_summary=AsyncMock(
            return_value=PeakSeasonRankSummary(result, result, result)
        ),
        fetch_autocard_summary=AsyncMock(return_value=result),
        current_peak_sub_key=lambda: 7,
    )
    game = SimpleNamespace(
        get_user_info=AsyncMock(return_value=SimpleNamespace(nick="player")),
        get_more_user_info=AsyncMock(
            return_value=SimpleNamespace(total_achieve=5760, pet_all_num=1231)
        ),
    )
    if outcome == "nick":
        game.get_user_info.side_effect = TimeoutError
    local = SimpleNamespace(
        config=SimpleNamespace(enabled=True),
        upsert_metrics=AsyncMock(return_value=LocalRankSummary()),
    )
    if outcome == "sample":
        local.upsert_metrics.side_effect = TimeoutError
    collection_base = AsyncMock(
        return_value=UnityPartOneInfo(pet_kind_num=1326, skin_num=79)
    )
    if outcome == "base":
        collection_base.side_effect = TimeoutError
    peak_base = AsyncMock(
        return_value=UnityPeakFetchResult(
            UnityPeakInfo(current_j_rank=3, current_k_rank=3, current_z_score=1421),
            frozenset(
                {"wild", "expert"}
                if outcome == "base"
                else {"standard", "wild", "expert"}
            ),
            (("standard", "unavailable"),) if outcome == "base" else (),
        )
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_part_one",
        collection_base,
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_peak_partial",
        peak_base,
    )
    reply = await fetch_player_shortcut_reply(
        _dependencies(rank, local),
        game,
        command=PlayerShortcutCommand(kind=kind, player_id=PLAYER_ID),
        player_id=PLAYER_ID,
    )
    assert reply.text
    assert reply.complete is (outcome in {"ok", "miss"})
