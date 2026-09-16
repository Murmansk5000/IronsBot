# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from functools import partial
from typing import Any, TypeVar

from ironsbot.services.seer.rank_constants import (
    ACHIEVE_RANK_KEY,
    ACHIEVE_RANK_SUB_KEY,
    AUTOCARD_RANK_KEY,
    AUTOCARD_RANK_SUB_KEY,
    BOOK_RANK_KEY,
    BOOK_RANK_SUB_KEY,
    COUNTERMARK_RANK_KEY,
    COUNTERMARK_RANK_SUB_KEY,
    EXPERT_PEAK_USER_RANK_KEY,
    MASTER_PEAK_USER_RANK_KEY,
    MOUNT_RANK_SUB_KEY,
    OUTFIT_PART_RANK_SUB_KEY,
    OUTFIT_RANK_KEY,
    OUTFIT_SUIT_RANK_SUB_KEY,
    PET_KIND_RANK_KEY,
    PET_KIND_RANK_SUB_KEY,
    SKIN_RANK_KEY,
    SKIN_RANK_SUB_KEY,
    STANDARD_PEAK_USER_RANK_KEY,
    WILD_PEAK_USER_RANK_KEY,
)
from ironsbot.services.seer.rank_models import (
    BookBreakdownSummary,
    PeakSeasonRankSummary,
    PlayerRankSummary,
    RankLookupResult,
    RankSummaryProgress,
)
from ironsbot.services.seer.rank_player_scheduler import PlayerRankLookupJob

FindRank = Callable[..., Awaitable[RankLookupResult]]
FindPetKindRank = Callable[..., Awaitable[RankLookupResult]]
RunLookupJobs = Callable[
    [Sequence[PlayerRankLookupJob]],
    Awaitable[dict[str, RankLookupResult]],
]
_LOGGER = logging.getLogger("ironsbot.seer.rank_summary")
SummaryT = TypeVar("SummaryT")


async def fetch_partial_rank_summary(
    operation: Awaitable[SummaryT],
    *,
    progress: RankSummaryProgress,
    timeout_seconds: float,
    build_partial: Callable[[dict[str, RankLookupResult], str], SummaryT],
) -> SummaryT:
    """Recover completed boards on failure, without swallowing cancellation."""
    try:
        return await asyncio.wait_for(operation, timeout=timeout_seconds)
    except Exception as error:  # noqa: BLE001
        _LOGGER.warning(
            "player rank summary interrupted: completed=%s last_started=%s",
            tuple(progress.completed),
            progress.current_title,
            exc_info=True,
        )
        return build_partial(progress.completed, _format_rank_failure(error))


def _display_rank_title(title: str) -> str:
    return title if title.endswith("榜") else f"{title}榜"


def _record_rank_error(
    errors: list[str] | None,
    *,
    title: str,
    error: Exception,
) -> None:
    if errors is None:
        return
    display_title = _display_rank_title(title)
    errors.append(f"{display_title}{_format_rank_failure(error)}")


def _format_rank_failure(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "查询超时"
    detail = str(error) or type(error).__name__
    return f"查询失败：{detail}"


async def _safe_find_rank(  # noqa: PLR0913
    label: str,
    find_rank: FindRank,
    game: Any,
    *,
    title: str,
    score_name: str,
    score: int | None = None,
    errors: list[str] | None = None,
    progress: RankSummaryProgress | None = None,
    **kwargs: Any,
) -> RankLookupResult:
    if progress is not None:
        progress.current_title = _display_rank_title(title)
    try:
        return await find_rank(
            game,
            title=title,
            score_name=score_name,
            **kwargs,
        )
    except (TimeoutError, OSError) as error:
        _LOGGER.warning("failed to fetch player rank item: %s", label, exc_info=True)
        _record_rank_error(errors, title=title, error=error)
        return RankLookupResult(
            title=title,
            score_name=score_name,
            score=score,
            failure=_format_rank_failure(error),
        )


async def _safe_find_pet_kind_rank(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    pet_kind_count: int,
    search_limit: int,
    find_pet_kind_rank: FindPetKindRank,
    errors: list[str] | None = None,
    progress: RankSummaryProgress | None = None,
    anchor_only: bool = False,
) -> RankLookupResult:
    title = "精灵图鉴"
    if progress is not None:
        progress.current_title = _display_rank_title(title)
    try:
        return await find_pet_kind_rank(
            game,
            user_id=user_id,
            pet_kind_count=pet_kind_count,
            search_limit=search_limit,
            anchor_only=anchor_only,
        )
    except (TimeoutError, OSError) as error:
        _LOGGER.warning("failed to fetch player rank item: pet_kind", exc_info=True)
        _record_rank_error(errors, title=title, error=error)
        return RankLookupResult(
            title=title,
            score_name="精灵",
            score=pet_kind_count,
            failure=_format_rank_failure(error),
        )


async def _find_current_peak_rank(  # noqa: PLR0913
    label: str,
    find_rank: FindRank,
    game: Any,
    *,
    user_id: int,
    title: str,
    score_name: str,
    key: int,
    sub_key: int,
    candidate_score: int | None,
    progress: RankSummaryProgress | None,
    anchor_only: bool,
) -> RankLookupResult:
    has_candidate_score = candidate_score is not None and candidate_score > 0
    if has_candidate_score:
        result = await _safe_find_rank(
            label,
            find_rank,
            game,
            user_id=user_id,
            title=title,
            score_name=score_name,
            score=candidate_score,
            key=key,
            sub_key=sub_key,
            target_score=candidate_score,
            progress=progress,
            anchor_only=anchor_only,
        )
        if result.cost.restricted_miss:
            result.failure = "缓存位置已变化，排名未确认"
        return result

    return await _safe_find_rank(
        label,
        find_rank,
        game,
        user_id=user_id,
        title=title,
        score_name=score_name,
        key=key,
        sub_key=sub_key,
        search_limit=0,
        progress=progress,
        anchor_only=anchor_only,
    )


async def fetch_book_breakdown_summary(  # noqa: PLR0913
    game: Any,
    user_id: int,
    *,
    pet_kind_count: int = 0,
    skin_score: int | None = None,
    limit: int,
    find_pet_kind_rank: FindPetKindRank,
    find_rank: FindRank,
    errors: list[str] | None = None,
    progress: RankSummaryProgress | None = None,
    anchor_only: bool = False,
) -> BookBreakdownSummary:
    pet_kind = await _safe_find_pet_kind_rank(
        game,
        user_id=user_id,
        pet_kind_count=pet_kind_count,
        search_limit=limit,
        find_pet_kind_rank=find_pet_kind_rank,
        errors=errors,
        progress=progress,
        anchor_only=anchor_only,
    )
    skin = await _safe_find_rank(
        "skin",
        find_rank,
        game,
        user_id=user_id,
        title="皮肤图鉴",
        score_name="皮肤",
        score=skin_score,
        key=SKIN_RANK_KEY,
        sub_key=SKIN_RANK_SUB_KEY,
        target_score=skin_score,
        search_limit=limit,
        errors=errors,
        progress=progress,
        anchor_only=anchor_only,
    )
    countermark = await _safe_find_rank(
        "countermark",
        find_rank,
        game,
        user_id=user_id,
        title="刻印图鉴",
        score_name="刻印",
        key=COUNTERMARK_RANK_KEY,
        sub_key=COUNTERMARK_RANK_SUB_KEY,
        search_limit=limit,
        errors=errors,
        progress=progress,
        anchor_only=anchor_only,
    )
    outfit_suit = await _safe_find_rank(
        "outfit_suit",
        find_rank,
        game,
        user_id=user_id,
        title="套装图鉴",
        score_name="套装",
        key=OUTFIT_RANK_KEY,
        sub_key=OUTFIT_SUIT_RANK_SUB_KEY,
        search_limit=limit,
        errors=errors,
        progress=progress,
        anchor_only=anchor_only,
    )
    outfit_part = await _safe_find_rank(
        "outfit_part",
        find_rank,
        game,
        user_id=user_id,
        title="部件图鉴",
        score_name="部件",
        key=OUTFIT_RANK_KEY,
        sub_key=OUTFIT_PART_RANK_SUB_KEY,
        search_limit=limit,
        errors=errors,
        progress=progress,
        anchor_only=anchor_only,
    )
    mount = await _safe_find_rank(
        "mount",
        find_rank,
        game,
        user_id=user_id,
        title="座驾图鉴",
        score_name="座驾",
        key=OUTFIT_RANK_KEY,
        sub_key=MOUNT_RANK_SUB_KEY,
        search_limit=limit,
        errors=errors,
        progress=progress,
        anchor_only=anchor_only,
    )
    return BookBreakdownSummary(
        pet_kind_count=pet_kind_count,
        pet_kind=pet_kind,
        skin=skin,
        countermark=countermark,
        outfit_suit=outfit_suit,
        outfit_part=outfit_part,
        mount=mount,
    )


async def fetch_peak_season_rank_summary(  # noqa: PLR0913
    game: Any,
    user_id: int,
    *,
    standard_score: int | None = None,
    wild_score: int | None = None,
    expert_score: int | None = None,
    current_peak_sub_key: int | None,
    find_rank: FindRank,
    current_master_sub_key: int | None = None,
    progress: RankSummaryProgress | None = None,
    anchor_only: bool = False,
    run_lookup_jobs: RunLookupJobs | None = None,
) -> PeakSeasonRankSummary:
    if current_peak_sub_key is None and current_master_sub_key is None:
        return PeakSeasonRankSummary.empty()

    specs: list[tuple[str, str, str, int, int, int | None]] = []
    if current_peak_sub_key is not None:
        specs.extend(
            (
                (
                    "standard_peak",
                    "竞技赛季榜",
                    "段位分",
                    STANDARD_PEAK_USER_RANK_KEY,
                    current_peak_sub_key,
                    standard_score,
                ),
                (
                    "wild_peak",
                    "狂野赛季榜",
                    "段位分",
                    WILD_PEAK_USER_RANK_KEY,
                    current_peak_sub_key,
                    wild_score,
                ),
                (
                    "expert_peak",
                    "专家赛季榜",
                    "专家积分",
                    EXPERT_PEAK_USER_RANK_KEY,
                    current_peak_sub_key,
                    expert_score,
                ),
            )
        )
    if current_master_sub_key is not None:
        specs.append(
            (
                "master_peak",
                "大师赛季榜",
                "段位分",
                MASTER_PEAK_USER_RANK_KEY,
                current_master_sub_key,
                None,
            )
        )
    jobs = tuple(
        PlayerRankLookupJob(
            id=job_id,
            title=title,
            key=key,
            sub_key=sub_key,
            user_id=user_id,
            target_score=candidate_score,
            operation=partial(
                _find_current_peak_rank,
                job_id,
                find_rank,
                game,
                user_id=user_id,
                title=title,
                score_name=score_name,
                key=key,
                sub_key=sub_key,
                candidate_score=candidate_score,
                progress=progress,
                anchor_only=anchor_only,
            ),
        )
        for job_id, title, score_name, key, sub_key, candidate_score in specs
    )
    results = await _run_lookup_jobs(jobs, run_lookup_jobs, progress)
    return PeakSeasonRankSummary.from_results(results)


async def fetch_autocard_rank_summary(
    game: Any,
    user_id: int,
    *,
    find_rank: FindRank,
    anchor_only: bool = False,
) -> RankLookupResult:
    return await find_rank(
        game,
        user_id=user_id,
        title="群星之巅榜",
        score_name="分",
        key=AUTOCARD_RANK_KEY,
        sub_key=AUTOCARD_RANK_SUB_KEY,
        anchor_only=anchor_only,
    )


async def fetch_player_rank_summary(  # noqa: PLR0913
    game: Any,
    user_id: int,
    *,
    book_score: int | None = None,
    achieve_score: int | None = None,
    pet_kind_count: int = 0,
    skin_score: int | None = None,
    book_breakdown_limit: int,
    find_rank: FindRank,
    find_pet_kind_rank: FindPetKindRank,
    progress: RankSummaryProgress | None = None,
    anchor_only: bool = False,
    run_lookup_jobs: RunLookupJobs | None = None,
) -> PlayerRankSummary:
    errors: list[str] = []
    jobs = (
        PlayerRankLookupJob(
            id="book",
            title="图鉴积分榜",
            key=BOOK_RANK_KEY,
            sub_key=BOOK_RANK_SUB_KEY,
            user_id=user_id,
            target_score=book_score,
            operation=lambda: _safe_find_rank(
                "book", find_rank, game, user_id=user_id, title="图鉴积分",
                score_name="图鉴积分", score=book_score, key=BOOK_RANK_KEY,
                sub_key=BOOK_RANK_SUB_KEY, target_score=book_score, errors=errors,
                progress=progress, anchor_only=anchor_only,
            ),
        ),
        PlayerRankLookupJob(
            id="achieve",
            title="成就点数榜",
            key=ACHIEVE_RANK_KEY,
            sub_key=ACHIEVE_RANK_SUB_KEY,
            user_id=user_id,
            target_score=achieve_score,
            operation=lambda: _safe_find_rank(
                "achieve", find_rank, game, user_id=user_id, title="成就点数",
                score_name="成就点数", score=achieve_score, key=ACHIEVE_RANK_KEY,
                sub_key=ACHIEVE_RANK_SUB_KEY, target_score=achieve_score,
                errors=errors, progress=progress, anchor_only=anchor_only,
            ),
        ),
        PlayerRankLookupJob(
            id="pet_kind",
            title="精灵图鉴榜",
            key=PET_KIND_RANK_KEY,
            sub_key=PET_KIND_RANK_SUB_KEY,
            user_id=user_id,
            target_score=pet_kind_count or None,
            operation=lambda: _safe_find_pet_kind_rank(
                game, user_id=user_id, pet_kind_count=pet_kind_count,
                search_limit=book_breakdown_limit,
                find_pet_kind_rank=find_pet_kind_rank, errors=errors,
                progress=progress, anchor_only=anchor_only,
            ),
        ),
        PlayerRankLookupJob(
            id="skin",
            title="皮肤图鉴榜",
            key=SKIN_RANK_KEY,
            sub_key=SKIN_RANK_SUB_KEY,
            user_id=user_id,
            target_score=skin_score,
            operation=lambda: _safe_find_rank(
                "skin", find_rank, game, user_id=user_id, title="皮肤图鉴",
                score_name="皮肤", score=skin_score, key=SKIN_RANK_KEY,
                sub_key=SKIN_RANK_SUB_KEY, target_score=skin_score,
                search_limit=book_breakdown_limit, errors=errors,
                progress=progress, anchor_only=anchor_only,
            ),
        ),
        PlayerRankLookupJob(
            id="countermark",
            title="刻印图鉴榜",
            key=COUNTERMARK_RANK_KEY,
            sub_key=COUNTERMARK_RANK_SUB_KEY,
            user_id=user_id,
            target_score=None,
            operation=lambda: _safe_find_rank(
                "countermark", find_rank, game, user_id=user_id, title="刻印图鉴",
                score_name="刻印", key=COUNTERMARK_RANK_KEY,
                sub_key=COUNTERMARK_RANK_SUB_KEY, search_limit=book_breakdown_limit,
                errors=errors, progress=progress, anchor_only=anchor_only,
            ),
        ),
        PlayerRankLookupJob(
            id="outfit_suit",
            title="套装图鉴榜",
            key=OUTFIT_RANK_KEY,
            sub_key=OUTFIT_SUIT_RANK_SUB_KEY,
            user_id=user_id,
            target_score=None,
            operation=lambda: _safe_find_rank(
                "outfit_suit", find_rank, game, user_id=user_id, title="套装图鉴",
                score_name="套装", key=OUTFIT_RANK_KEY,
                sub_key=OUTFIT_SUIT_RANK_SUB_KEY, search_limit=book_breakdown_limit,
                errors=errors, progress=progress, anchor_only=anchor_only,
            ),
        ),
        PlayerRankLookupJob(
            id="outfit_part",
            title="部件图鉴榜",
            key=OUTFIT_RANK_KEY,
            sub_key=OUTFIT_PART_RANK_SUB_KEY,
            user_id=user_id,
            target_score=None,
            operation=lambda: _safe_find_rank(
                "outfit_part", find_rank, game, user_id=user_id, title="部件图鉴",
                score_name="部件", key=OUTFIT_RANK_KEY,
                sub_key=OUTFIT_PART_RANK_SUB_KEY, search_limit=book_breakdown_limit,
                errors=errors, progress=progress, anchor_only=anchor_only,
            ),
        ),
        PlayerRankLookupJob(
            id="mount",
            title="座驾图鉴榜",
            key=OUTFIT_RANK_KEY,
            sub_key=MOUNT_RANK_SUB_KEY,
            user_id=user_id,
            target_score=None,
            operation=lambda: _safe_find_rank(
                "mount", find_rank, game, user_id=user_id, title="座驾图鉴",
                score_name="座驾", key=OUTFIT_RANK_KEY,
                sub_key=MOUNT_RANK_SUB_KEY, search_limit=book_breakdown_limit,
                errors=errors, progress=progress, anchor_only=anchor_only,
            ),
        ),
    )
    results = await _run_lookup_jobs(jobs, run_lookup_jobs, progress)
    return PlayerRankSummary.from_results(
        results,
        pet_kind_count=pet_kind_count,
        errors=tuple(errors),
    )


async def _run_lookup_jobs(
    jobs: Sequence[PlayerRankLookupJob],
    runner: RunLookupJobs | None,
    progress: RankSummaryProgress | None,
) -> dict[str, RankLookupResult]:
    async def record(job: PlayerRankLookupJob) -> RankLookupResult:
        try:
            result = await job.operation()
        except Exception as error:  # noqa: BLE001
            _LOGGER.warning("player rank item failed: %s", job.id, exc_info=True)
            result = RankLookupResult(
                title=job.title,
                score_name="",
                score=job.target_score,
                failure=_format_rank_failure(error),
            )
        if progress is not None:
            progress.completed[job.id] = result
        return result

    tracked_jobs = tuple(replace(job, operation=partial(record, job)) for job in jobs)
    if runner is not None:
        return await runner(tracked_jobs)
    return {job.id: await job.operation() for job in tracked_jobs}
