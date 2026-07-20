# SPDX-License-Identifier: GPL-3.0-or-later
import logging
from collections.abc import Awaitable, Callable
from typing import Any

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
    MOUNT_RANK_SUB_KEY,
    OUTFIT_PART_RANK_SUB_KEY,
    OUTFIT_RANK_KEY,
    OUTFIT_SUIT_RANK_SUB_KEY,
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

FindRank = Callable[..., Awaitable[RankLookupResult]]
FindPetKindRank = Callable[..., Awaitable[RankLookupResult]]
_LOGGER = logging.getLogger("ironsbot.seer.rank_summary")


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
        )
        if result.rank is not None or not result.queried:
            return result

    return await _safe_find_rank(
        f"{label}_current_season",
        find_rank,
        game,
        user_id=user_id,
        title=title,
        score_name=score_name,
        key=key,
        sub_key=sub_key,
        search_limit=None if has_candidate_score else 0,
        progress=progress,
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
) -> BookBreakdownSummary:
    pet_kind = await _safe_find_pet_kind_rank(
        game,
        user_id=user_id,
        pet_kind_count=pet_kind_count,
        search_limit=limit,
        find_pet_kind_rank=find_pet_kind_rank,
        errors=errors,
        progress=progress,
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
    progress: RankSummaryProgress | None = None,
) -> PeakSeasonRankSummary:
    if current_peak_sub_key is None:
        return PeakSeasonRankSummary.empty()

    summary = PeakSeasonRankSummary.empty()
    summary.standard = await _find_current_peak_rank(
        "standard_peak",
        find_rank,
        game,
        user_id=user_id,
        title="竞技赛季榜",
        score_name="段位分",
        key=STANDARD_PEAK_USER_RANK_KEY,
        sub_key=current_peak_sub_key,
        candidate_score=standard_score,
        progress=progress,
    )
    summary.wild = await _find_current_peak_rank(
        "wild_peak",
        find_rank,
        game,
        user_id=user_id,
        title="狂野赛季榜",
        score_name="段位分",
        key=WILD_PEAK_USER_RANK_KEY,
        sub_key=current_peak_sub_key,
        candidate_score=wild_score,
        progress=progress,
    )
    summary.expert = await _find_current_peak_rank(
        "expert_peak",
        find_rank,
        game,
        user_id=user_id,
        title="专家赛季榜",
        score_name="专家积分",
        key=EXPERT_PEAK_USER_RANK_KEY,
        sub_key=current_peak_sub_key,
        candidate_score=expert_score,
        progress=progress,
    )
    return summary


async def fetch_autocard_rank_summary(
    game: Any,
    user_id: int,
    *,
    find_rank: FindRank,
) -> RankLookupResult:
    return await find_rank(
        game,
        user_id=user_id,
        title="群星之巅榜",
        score_name="分",
        key=AUTOCARD_RANK_KEY,
        sub_key=AUTOCARD_RANK_SUB_KEY,
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
) -> PlayerRankSummary:
    errors: list[str] = []
    book = await _safe_find_rank(
        "book",
        find_rank,
        game,
        user_id=user_id,
        title="图鉴积分",
        score_name="图鉴积分",
        score=book_score,
        key=BOOK_RANK_KEY,
        sub_key=BOOK_RANK_SUB_KEY,
        target_score=book_score,
        errors=errors,
        progress=progress,
    )
    achieve = await _safe_find_rank(
        "achieve",
        find_rank,
        game,
        user_id=user_id,
        title="成就点数",
        score_name="成就点数",
        score=achieve_score,
        key=ACHIEVE_RANK_KEY,
        sub_key=ACHIEVE_RANK_SUB_KEY,
        target_score=achieve_score,
        errors=errors,
        progress=progress,
    )
    breakdown = await fetch_book_breakdown_summary(
        game,
        user_id,
        pet_kind_count=pet_kind_count,
        skin_score=skin_score,
        limit=book_breakdown_limit,
        find_pet_kind_rank=find_pet_kind_rank,
        find_rank=find_rank,
        errors=errors,
        progress=progress,
    )
    return PlayerRankSummary(
        book=book,
        achieve=achieve,
        breakdown=breakdown,
        errors=tuple(errors),
    )
