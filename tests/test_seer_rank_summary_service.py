import asyncio
from collections.abc import Sequence

import pytest

from ironsbot.config.models.seer import PlayerRankLookupConfig
from ironsbot.services.seer.rank_constants import (
    ACHIEVE_RANK_KEY,
    EXPERT_PEAK_USER_RANK_KEY,
    MASTER_PEAK_USER_RANK_KEY,
    SKIN_RANK_KEY,
    STANDARD_PEAK_USER_RANK_KEY,
    WILD_PEAK_USER_RANK_KEY,
)
from ironsbot.services.seer.rank_models import (
    PeakSeasonRankSummary,
    PlayerRankSummary,
    RankLookupResult,
    RankSummaryProgress,
)
from ironsbot.services.seer.rank_player_scheduler import (
    PlayerRankLookupJob,
    current_player_rank_page_scheduler,
    run_player_rank_lookup_jobs,
)
from ironsbot.services.seer.rank_summary import (
    fetch_partial_rank_summary,
    fetch_peak_season_rank_summary,
    fetch_player_rank_summary,
)

USER_ID = 123456
FOUND_RANK = 7
PET_KIND_COUNT = 100
SKIN_SCORE = 10
ACHIEVE_SCORE = 56
PEAK_SCORE = 400100
EXPERT_SCORE = 2500
CURRENT_PEAK_SCORE = 300033
CURRENT_PEAK_RANK = 33
CURRENT_PEAK_LINEAR_RANK = 12
PEAK_MODE_COUNT = 3
MASTER_SUB_KEY = 20260904


def _int_kwarg(kwargs: dict[str, object], name: str, default: int = 0) -> int:
    value = kwargs.get(name)
    return value if isinstance(value, int) else default


async def _rank_success(_game: object, **kwargs: object) -> RankLookupResult:
    return RankLookupResult(
        title=str(kwargs["title"]),
        score_name=str(kwargs["score_name"]),
        rank=FOUND_RANK,
        score=_int_kwarg(kwargs, "target_score", 10),
        searched_limit=_int_kwarg(kwargs, "search_limit"),
        queried=True,
    )


async def _pet_kind_success(_game: object, **kwargs: object) -> RankLookupResult:
    return RankLookupResult(
        title="精灵图鉴",
        score_name="精灵",
        rank=8,
        score=_int_kwarg(kwargs, "pet_kind_count"),
        queried=True,
    )


@pytest.mark.asyncio
async def test_player_rank_summary_keeps_other_items_when_one_rank_times_out() -> None:
    async def find_rank(game: object, **kwargs: object) -> RankLookupResult:
        if kwargs["key"] in {ACHIEVE_RANK_KEY, SKIN_RANK_KEY}:
            raise TimeoutError
        return await _rank_success(game, **kwargs)

    summary = await fetch_player_rank_summary(
        object(),
        USER_ID,
        achieve_score=ACHIEVE_SCORE,
        pet_kind_count=PET_KIND_COUNT,
        skin_score=SKIN_SCORE,
        book_breakdown_limit=2000,
        find_rank=find_rank,
        find_pet_kind_rank=_pet_kind_success,
    )

    assert summary.book.queried
    assert summary.book.rank == FOUND_RANK
    assert not summary.achieve.queried
    assert summary.achieve.score == ACHIEVE_SCORE
    assert summary.breakdown.pet_kind is not None
    assert summary.breakdown.skin is not None
    assert summary.breakdown.countermark is not None
    assert summary.breakdown.pet_kind.queried
    assert not summary.breakdown.skin.queried
    assert summary.breakdown.skin.score == SKIN_SCORE
    assert summary.breakdown.countermark.queried
    assert summary.errors == (
        "成就点数榜查询超时",
        "皮肤图鉴榜查询超时",
    )


@pytest.mark.asyncio
async def test_peak_rank_summary_keeps_other_modes_when_one_rank_times_out() -> None:
    async def find_rank(game: object, **kwargs: object) -> RankLookupResult:
        if kwargs["key"] == WILD_PEAK_USER_RANK_KEY:
            raise TimeoutError
        return await _rank_success(game, **kwargs)

    summary = await fetch_peak_season_rank_summary(
        object(),
        USER_ID,
        standard_score=PEAK_SCORE,
        wild_score=PEAK_SCORE,
        expert_score=EXPERT_SCORE,
        current_peak_sub_key=42,
        find_rank=find_rank,
    )

    assert summary.standard.queried
    assert summary.standard.rank == FOUND_RANK
    assert not summary.wild.queried
    assert summary.wild.score == PEAK_SCORE
    assert summary.wild.failure == "查询超时"
    assert summary.expert.queried
    assert summary.expert.score == EXPERT_SCORE


@pytest.mark.asyncio
async def test_peak_rank_summary_queries_master_with_its_own_season() -> None:
    calls: list[dict[str, object]] = []

    async def find_rank(_game: object, **kwargs: object) -> RankLookupResult:
        calls.append(kwargs)
        return await _rank_success(_game, **kwargs)

    summary = await fetch_peak_season_rank_summary(
        object(),
        USER_ID,
        current_peak_sub_key=None,
        current_master_sub_key=MASTER_SUB_KEY,
        find_rank=find_rank,
    )

    assert len(calls) == 1
    assert calls[0]["key"] == MASTER_PEAK_USER_RANK_KEY
    assert calls[0]["sub_key"] == MASTER_SUB_KEY
    assert "target_score" not in calls[0]
    assert calls[0]["search_limit"] is None
    assert summary.master.queried
    assert not summary.standard.queried


@pytest.mark.asyncio
async def test_peak_rank_summary_keeps_expert_score_when_expert_times_out() -> None:
    async def find_rank(game: object, **kwargs: object) -> RankLookupResult:
        if kwargs["key"] == EXPERT_PEAK_USER_RANK_KEY:
            raise TimeoutError
        return await _rank_success(game, **kwargs)

    summary = await fetch_peak_season_rank_summary(
        object(),
        USER_ID,
        standard_score=0,
        wild_score=0,
        expert_score=EXPERT_SCORE,
        current_peak_sub_key=42,
        find_rank=find_rank,
    )

    assert not summary.expert.queried
    assert summary.expert.score == EXPERT_SCORE
    assert summary.expert.failure == "查询超时"


def test_peak_rank_summary_reuses_completed_results_and_marks_all_missing() -> None:
    expert = RankLookupResult(title="专家赛季榜", score_name="分", rank=4)
    summary = PeakSeasonRankSummary.from_results(
        {"expert_peak": expert},
        failure="查询超时",
    )

    assert summary.standard.failure == "查询超时"
    assert summary.wild.failure == "查询超时"
    assert summary.expert is expert
    assert expert.failure is None


def test_player_rank_summary_preserves_existing_failure_on_recovery() -> None:
    book = RankLookupResult(title="图鉴积分", score_name="分", failure="连接断开")
    summary = PlayerRankSummary.from_results({"book": book}, failure="查询超时")

    assert summary.book is book
    assert summary.book.failure == "连接断开"
    assert summary.achieve.failure == "查询超时"
    assert summary.breakdown.pet_kind is not None
    assert summary.breakdown.pet_kind.failure == "查询超时"


def test_peak_rank_summary_marks_all_modes_when_the_whole_section_fails() -> None:
    summary = PeakSeasonRankSummary.from_results({}, failure="查询超时")

    assert summary.standard.failure == "查询超时"
    assert summary.wild.failure == "查询超时"
    assert summary.expert.failure == "查询超时"
    assert summary.master.failure == "查询超时"


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_partial_summary_preserves_failure_and_propagates_cancellation(
    *,
    cancel: bool,
) -> None:
    progress = RankSummaryProgress()
    found = asyncio.Event()
    waiting = asyncio.Event()
    drained = asyncio.Event()

    async def find_rank(_game: object, **kwargs: object) -> RankLookupResult:
        if kwargs["key"] == WILD_PEAK_USER_RANK_KEY:
            message = "invalid rank response"
            raise ValueError(message)
        if kwargs["key"] == EXPERT_PEAK_USER_RANK_KEY:
            found.set()
            return await _rank_success(_game, **kwargs)
        scheduler = current_player_rank_page_scheduler()
        assert scheduler is not None

        async def page() -> None:
            waiting.set()
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()

        await scheduler.fetch_page("standard", page)
        raise AssertionError

    async def runner(
        jobs: Sequence[PlayerRankLookupJob],
    ) -> dict[str, RankLookupResult]:
        return await run_player_rank_lookup_jobs(jobs, PlayerRankLookupConfig())

    operation = fetch_peak_season_rank_summary(
        object(),
        USER_ID,
        current_peak_sub_key=7,
        find_rank=find_rank,
        standard_score=PEAK_SCORE,
        wild_score=PEAK_SCORE,
        expert_score=EXPERT_SCORE,
        progress=progress,
        run_lookup_jobs=runner,
    )
    task = asyncio.create_task(
        fetch_partial_rank_summary(
            operation,
            progress=progress,
            timeout_seconds=1 if cancel else 0.05,
            build_partial=lambda results, failure: PeakSeasonRankSummary.from_results(
                results,
                failure=failure,
            ),
        )
    )
    await asyncio.wait_for(found.wait(), timeout=1)
    await asyncio.wait_for(waiting.wait(), timeout=1)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        summary = await task
        assert summary.expert is progress.completed["expert_peak"]
        assert summary.expert.rank == FOUND_RANK
        assert summary.standard.failure == "查询超时"
        assert summary.wild.failure == "查询失败：invalid rank response"
    assert drained.is_set()
    assert set(progress.completed) == {"expert_peak", "wild_peak"}
    assert current_player_rank_page_scheduler() is None


@pytest.mark.asyncio
async def test_peak_rank_summary_does_not_linearly_rescan_stale_candidate(
) -> None:
    calls: list[tuple[int, int | None]] = []

    async def find_rank(_game: object, **kwargs: object) -> RankLookupResult:
        key = _int_kwarg(kwargs, "key")
        target_score = kwargs.get("target_score")
        calls.append(
            (key, target_score if isinstance(target_score, int) else None)
        )
        if key == WILD_PEAK_USER_RANK_KEY:
            return RankLookupResult(
                title=str(kwargs["title"]),
                score_name=str(kwargs["score_name"]),
                rank=None,
                score=PEAK_SCORE if target_score is not None else None,
                searched_limit=2000,
                queried=True,
            )
        return await _rank_success(_game, **kwargs)

    summary = await fetch_peak_season_rank_summary(
        object(),
        USER_ID,
        standard_score=PEAK_SCORE,
        wild_score=PEAK_SCORE,
        expert_score=EXPERT_SCORE,
        current_peak_sub_key=20260717,
        find_rank=find_rank,
    )

    assert calls.count((WILD_PEAK_USER_RANK_KEY, PEAK_SCORE)) == 1
    assert calls.count((WILD_PEAK_USER_RANK_KEY, None)) == 0
    assert summary.wild.queried
    assert summary.wild.rank is None
    assert summary.wild.score == PEAK_SCORE


@pytest.mark.asyncio
async def test_peak_rank_summary_reaches_expert_after_earlier_score_misses(
) -> None:
    calls: list[int] = []

    async def find_rank(_game: object, **kwargs: object) -> RankLookupResult:
        key = _int_kwarg(kwargs, "key")
        calls.append(key)
        rank = CURRENT_PEAK_RANK if key == EXPERT_PEAK_USER_RANK_KEY else None
        return RankLookupResult(
            title=str(kwargs["title"]),
            score_name=str(kwargs["score_name"]),
            rank=rank,
            score=_int_kwarg(kwargs, "target_score") or None,
            searched_limit=2000,
            queried=True,
        )

    summary = await fetch_peak_season_rank_summary(
        object(),
        USER_ID,
        standard_score=PEAK_SCORE,
        wild_score=PEAK_SCORE,
        expert_score=EXPERT_SCORE,
        current_peak_sub_key=20260717,
        find_rank=find_rank,
    )

    assert calls == [
        STANDARD_PEAK_USER_RANK_KEY,
        WILD_PEAK_USER_RANK_KEY,
        EXPERT_PEAK_USER_RANK_KEY,
    ]
    assert summary.expert.rank == CURRENT_PEAK_RANK
    assert summary.expert.score == EXPERT_SCORE


@pytest.mark.asyncio
async def test_peak_rank_summary_does_not_report_restricted_cache_miss_as_unranked(
) -> None:
    async def find_rank(_game: object, **kwargs: object) -> RankLookupResult:
        result = RankLookupResult(
            title=str(kwargs["title"]),
            score_name=str(kwargs["score_name"]),
            score=_int_kwarg(kwargs, "target_score") or None,
            searched_limit=10_000,
            queried=True,
        )
        result.cost.restricted_miss = True
        return result

    summary = await fetch_peak_season_rank_summary(
        object(),
        USER_ID,
        standard_score=PEAK_SCORE,
        wild_score=PEAK_SCORE,
        expert_score=EXPERT_SCORE,
        current_peak_sub_key=20260717,
        find_rank=find_rank,
        anchor_only=True,
    )

    assert summary.expert.rank is None
    assert summary.expert.failure == "缓存位置已变化，排名未确认"


@pytest.mark.asyncio
async def test_peak_rank_summary_queries_current_season_without_candidate_score(
) -> None:
    calls: list[dict[str, object]] = []

    async def find_rank(_game: object, **kwargs: object) -> RankLookupResult:
        calls.append(kwargs)
        return RankLookupResult(
            title=str(kwargs["title"]),
            score_name=str(kwargs["score_name"]),
            rank=CURRENT_PEAK_LINEAR_RANK,
            score=CURRENT_PEAK_SCORE,
            searched_limit=2000,
            queried=True,
        )

    summary = await fetch_peak_season_rank_summary(
        object(),
        USER_ID,
        current_peak_sub_key=20260717,
        find_rank=find_rank,
    )

    assert len(calls) == PEAK_MODE_COUNT
    assert all("target_score" not in call for call in calls)
    assert all(call["search_limit"] == 0 for call in calls)
    assert summary.standard.rank == CURRENT_PEAK_LINEAR_RANK
    assert summary.standard.score == CURRENT_PEAK_SCORE


@pytest.mark.asyncio
async def test_player_rank_summary_tracks_current_rank_title() -> None:
    progress = RankSummaryProgress()

    await fetch_player_rank_summary(
        object(),
        USER_ID,
        pet_kind_count=PET_KIND_COUNT,
        book_breakdown_limit=2000,
        find_rank=_rank_success,
        find_pet_kind_rank=_pet_kind_success,
        progress=progress,
    )

    assert progress.current_title == "座驾图鉴榜"
