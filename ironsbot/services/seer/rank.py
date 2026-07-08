# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import time
from datetime import datetime
from typing import Any

from nonebot import logger

from ironsbot.config import get_app_config
from ironsbot.config.models.seer import LocalRankConfig, RankQueryConfig
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
    PET_KIND_RANK_ANOMALY_COUNT,
    PET_KIND_RANK_ANOMALY_USER_IDS,
    PET_KIND_RANK_KEY,
    PET_KIND_RANK_SUB_KEY,
    SKIN_RANK_KEY,
    SKIN_RANK_SUB_KEY,
    STANDARD_PEAK_USER_RANK_KEY,
    WILD_PEAK_USER_RANK_KEY,
)
from ironsbot.services.seer.rank_fetching import fetch_rank_page_result_from_game
from ironsbot.services.seer.rank_formatting import (
    format_book_breakdown as _format_book_breakdown,
)
from ironsbot.services.seer.rank_formatting import (
    format_peak_rank_lookup as _format_peak_rank_lookup,
)
from ironsbot.services.seer.rank_formatting import (
    format_player_rank_summary as _format_player_rank_summary,
)
from ironsbot.services.seer.rank_formatting import (
    format_rank_lookup as _format_rank_lookup,
)
from ironsbot.services.seer.rank_models import (
    BookBreakdownSummary,
    PeakSeasonRankSummary,
    PlayerRankSummary,
    RankLookupResult,
    RankPageResult,
    RankScoreMissProof,
    RankScoreSearchResult,
)
from ironsbot.services.seer.rank_page_cache import (
    get_cached_rank_item,
    get_cached_rank_item_by_index,
    get_cached_rank_page_result,
    get_cached_rank_score_indexes,
    get_rank_page_cache_summary,
    save_rank_page,
)
from ironsbot.services.seer.rank_pagination import (
    rank_page_size,
    rank_page_start,
    rank_window_page_starts,
)
from ironsbot.services.seer.rank_position_cache import (
    find_rank_by_cached_position as _find_rank_by_cached_position_impl,
)
from ironsbot.services.seer.rank_position_cache import (
    refresh_cached_rank_window as _refresh_cached_rank_window_impl,
)
from ironsbot.services.seer.rank_score_cache import (
    cached_score_candidate_page_starts as _cached_score_candidate_page_starts_impl,
)
from ironsbot.services.seer.rank_score_cache import (
    cached_score_miss_boundary as _cached_score_miss_boundary_impl,
)
from ironsbot.services.seer.rank_score_cache import (
    fetch_rank_score_segment_from_cached_candidates as _fetch_cached_score_segment_impl,
)
from ironsbot.services.seer.rank_score_helpers import (
    score_miss_proof_from_page as _score_miss_proof_from_page,
)
from ironsbot.services.seer.rank_score_search import (
    RankScoreSegmentDependencies,
    score_search_probe_limit,
    score_search_tie_page_limit,
)
from ironsbot.services.seer.rank_score_search import (
    fetch_rank_score_segment as _fetch_rank_score_segment_impl,
)
from ironsbot.services.seer.rank_score_search import (
    find_last_existing_score_index as _find_last_existing_score_index,
)
from ironsbot.services.seer.rank_score_search import (
    find_rank_by_score as _find_rank_by_score_impl,
)

format_book_breakdown = _format_book_breakdown
format_peak_rank_lookup = _format_peak_rank_lookup
format_player_rank_summary = _format_player_rank_summary
format_rank_lookup = _format_rank_lookup

BOOK_BREAKDOWN_SCAN_LIMIT = 2_000
CACHED_RANK_LOOKUP_WINDOW_PAGES = 2
_RANK_WINDOW_REFRESH_KEYS: set[tuple[int, int, int, int]] = set()
_RANK_WINDOW_REFRESH_TASKS: set[asyncio.Task[None]] = set()


def get_rank_query_config() -> RankQueryConfig:
    return get_app_config().seer.rank


def get_local_rank_config() -> LocalRankConfig:
    return get_app_config().seer.local_rank


def _rank_page_size() -> int:
    return rank_page_size(get_rank_query_config())


def _rank_page_start(index: int) -> int:
    return rank_page_start(index, page_size=_rank_page_size())


def is_pet_kind_rank_anomaly_user(user_id: int) -> bool:
    return user_id in PET_KIND_RANK_ANOMALY_USER_IDS


async def _fetch_rank_page_result(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
    use_cache: bool = False,
) -> RankPageResult:
    return await fetch_rank_page_result_from_game(
        game,
        key=key,
        sub_key=sub_key,
        start=start,
        end=end,
        use_cache=use_cache,
        get_cached_page=get_cached_rank_page_result,
        save_page=save_rank_page,
    )


async def _fetch_rank_page(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
    use_cache: bool = False,
) -> list[Any]:
    result = await _fetch_rank_page_result(
        game,
        key=key,
        sub_key=sub_key,
        start=start,
        end=end,
        use_cache=use_cache,
    )
    return result.items


def _rank_window_page_starts(*, center_index: int, page_size: int) -> list[int]:
    return rank_window_page_starts(
        center_index=center_index,
        page_size=page_size,
        window_pages=CACHED_RANK_LOOKUP_WINDOW_PAGES,
    )


async def _refresh_cached_rank_window(
    game: Any,
    *,
    key: int,
    sub_key: int,
    center_index: int,
    page_size: int,
) -> None:
    await _refresh_cached_rank_window_impl(
        game,
        key=key,
        sub_key=sub_key,
        center_index=center_index,
        page_size=page_size,
        rank_window_page_starts=_rank_window_page_starts,
        fetch_rank_page=_fetch_rank_page,
        refresh_interval_seconds=get_local_rank_config().refresh_interval_seconds,
    )


def _schedule_cached_rank_window_refresh(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    center_index: int,
    page_size: int,
    fetched_at: float,
) -> None:
    if not get_rank_query_config().refresh_stale_cache:
        return

    ttl = get_rank_query_config().page_cache_ttl_seconds
    if ttl <= 0 or time.time() - fetched_at < ttl:
        return

    page_start = center_index // page_size * page_size
    refresh_key = (key, sub_key, page_start, page_size)
    if refresh_key in _RANK_WINDOW_REFRESH_KEYS:
        return

    async def run() -> None:
        try:
            await _refresh_cached_rank_window(
                game,
                key=key,
                sub_key=sub_key,
                center_index=center_index,
                page_size=page_size,
            )
        finally:
            _RANK_WINDOW_REFRESH_KEYS.discard(refresh_key)

    task = asyncio.create_task(run())
    _RANK_WINDOW_REFRESH_KEYS.add(refresh_key)
    _RANK_WINDOW_REFRESH_TASKS.add(task)

    def done_callback(done_task: asyncio.Task[None]) -> None:
        _RANK_WINDOW_REFRESH_TASKS.discard(done_task)
        try:
            done_task.result()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"rank window background refresh failed: {e}")

    task.add_done_callback(done_callback)


async def _find_rank_by_cached_position(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    page_size: int,
    result: RankLookupResult,
) -> RankLookupResult | None:
    return await _find_rank_by_cached_position_impl(
        game,
        user_id=user_id,
        key=key,
        sub_key=sub_key,
        page_size=page_size,
        result=result,
        get_cached_rank_item=get_cached_rank_item,
        rank_window_page_starts=_rank_window_page_starts,
        fetch_rank_page=_fetch_rank_page,
    )


async def _fetch_rank_item(
    game: Any,
    *,
    key: int,
    sub_key: int,
    index: int,
    use_cache: bool = False,
) -> Any | None:
    if use_cache:
        cached_item = get_cached_rank_item_by_index(
            key=key,
            sub_key=sub_key,
            rank_index=index,
        )
        if cached_item is not None:
            return cached_item

    page_size = _rank_page_size()
    page_start = _rank_page_start(index)
    items = await _fetch_rank_page(
        game,
        key=key,
        sub_key=sub_key,
        start=page_start,
        end=page_start + page_size - 1,
        use_cache=use_cache,
    )
    offset = index - page_start
    return items[offset] if 0 <= offset < len(items) else None


async def fetch_daily_rank_page(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    count: int,
    use_cache: bool = False,
) -> list[Any]:
    if count <= 0:
        return []

    result = await fetch_daily_rank_page_result(
        game,
        key=key,
        sub_key=sub_key,
        start=start,
        count=count,
        use_cache=use_cache,
    )
    return result.items


async def fetch_daily_rank_page_result(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    count: int,
    use_cache: bool = False,
) -> RankPageResult:
    if count <= 0:
        return RankPageResult(items=[], fetched_at=time.time())

    request_start = max(0, start)
    request_end = request_start + count - 1
    page_size = _rank_page_size()
    first_page_start = request_start // page_size * page_size
    last_page_start = request_end // page_size * page_size
    items: list[Any] = []
    fetched_times: list[float] = []

    for page_start in range(first_page_start, last_page_start + 1, page_size):
        page_result = await _fetch_rank_page_result(
            game,
            key=key,
            sub_key=sub_key,
            start=page_start,
            end=page_start + page_size - 1,
            use_cache=use_cache,
        )
        fetched_times.append(page_result.fetched_at)
        for offset, item in enumerate(page_result.items):
            rank_index = page_start + offset
            if rank_index > request_end:
                break
            if rank_index >= request_start:
                items.append(item)

        if len(page_result.items) < page_size:
            break

    return RankPageResult(
        items=items,
        fetched_at=max(fetched_times, default=time.time()),
    )


def _datetime_to_sub_key(value: datetime) -> int:
    return int(value.strftime("%Y%m%d"))


def get_current_peak_sub_key() -> int | None:
    if get_rank_query_config().peak_subkey is not None:
        return get_rank_query_config().peak_subkey

    try:
        from seerapi_models import PeakSeasonORM

        from ironsbot.integrations.db_registry import db_manager
    except Exception:  # noqa: BLE001
        return None

    session_gen = db_manager.get_session("seerapi")
    if session_gen is None:
        return None

    try:
        session = next(session_gen)
        season = session.get(PeakSeasonORM, 1)
        if season is None:
            return None
        return _datetime_to_sub_key(season.start_time)
    except Exception:  # noqa: BLE001
        return None
    finally:
        session_gen.close()


async def _find_rank_by_linear_scan(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    limit: int,
    page_size: int,
    result: RankLookupResult,
) -> RankLookupResult:
    start = 0
    while start < limit:
        end = min(start + page_size - 1, limit - 1)
        items = await _fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=end,
        )

        for offset, item in enumerate(items):
            if item.id == user_id:
                result.rank = start + offset + 1
                result.score = item.score
                return result

        if len(items) < end - start + 1:
            return result

        start = end + 1

    return result


def _score_search_probe_limit(limit: int) -> int:
    return score_search_probe_limit(get_rank_query_config(), limit)


def _score_search_tie_page_limit() -> int:
    return score_search_tie_page_limit(get_rank_query_config())


async def _find_rank_by_score(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    target_score: int,
    limit: int,
    page_size: int,
    result: RankLookupResult,
) -> RankLookupResult:
    return await _find_rank_by_score_impl(
        game,
        user_id=user_id,
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        limit=limit,
        page_size=page_size,
        result=result,
        score_search_probe_limit=_score_search_probe_limit,
        score_search_tie_page_limit=_score_search_tie_page_limit,
        find_last_existing_score_index=_find_last_existing_score_index,
        fetch_rank_item=_fetch_rank_item,
        fetch_rank_page=_fetch_rank_page,
    )


def _cached_score_candidate_page_starts(
    *,
    key: int,
    sub_key: int,
    target_score: int,
    start_index: int,
    end_index: int,
) -> list[int]:
    return _cached_score_candidate_page_starts_impl(
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_page_start=_rank_page_start,
        get_cached_score_indexes=get_cached_rank_score_indexes,
        get_cache_summary=get_rank_page_cache_summary,
    )


def _cached_score_miss_boundary(  # noqa: PLR0913
    *,
    key: int,
    sub_key: int,
    target_score: int,
    start_index: int,
    end_index: int,
    rank_offset: int,
) -> RankScoreMissProof | None:
    return _cached_score_miss_boundary_impl(
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_offset=rank_offset,
        get_cache_summary=get_rank_page_cache_summary,
        get_cached_score_indexes=get_cached_rank_score_indexes,
        get_cached_page_result=get_cached_rank_page_result,
        score_miss_proof_from_page=_score_miss_proof_from_page,
    )


async def _fetch_rank_score_segment_from_cached_candidates(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    target_score: int,
    start_index: int,
    end_index: int,
    rank_offset: int,
    result: RankScoreSearchResult,
    candidate_starts: list[int],
) -> RankScoreSearchResult | None:
    return await _fetch_cached_score_segment_impl(
        game,
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_offset=rank_offset,
        result=result,
        candidate_starts=candidate_starts,
        rank_page_size=_rank_page_size,
        rank_page_start=_rank_page_start,
        score_search_tie_page_limit=_score_search_tie_page_limit,
        fetch_rank_page_result=_fetch_rank_page_result,
    )


async def fetch_rank_score_segment(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    title: str,
    score_name: str,
    target_score: int,
    search_limit: int | None = None,
    start_index: int = 0,
    rank_offset: int = 0,
) -> RankScoreSearchResult:
    deps = RankScoreSegmentDependencies(
        score_search_limit=_score_search_limit,
        rank_page_size=_rank_page_size,
        rank_page_start=_rank_page_start,
        cached_score_miss_boundary=_cached_score_miss_boundary,
        cached_score_candidate_page_starts=_cached_score_candidate_page_starts,
        fetch_cached_candidates=_fetch_rank_score_segment_from_cached_candidates,
        score_search_probe_limit=_score_search_probe_limit,
        score_search_tie_page_limit=_score_search_tie_page_limit,
        find_last_existing_score_index=_find_last_existing_score_index,
        fetch_rank_item=_fetch_rank_item,
        fetch_rank_page_result=_fetch_rank_page_result,
        score_miss_proof_from_page=_score_miss_proof_from_page,
    )
    return await _fetch_rank_score_segment_impl(
        game,
        key=key,
        sub_key=sub_key,
        title=title,
        score_name=score_name,
        target_score=target_score,
        search_limit=search_limit,
        start_index=start_index,
        rank_offset=rank_offset,
        deps=deps,
    )


def _online_search_limit(search_limit: int | None = None) -> int:
    rank_config = get_rank_query_config()
    configured_limit = max(0, rank_config.limit)
    requested_limit = configured_limit if search_limit is None else max(0, search_limit)
    return min(requested_limit, max(0, rank_config.online_limit))


def _score_search_limit(search_limit: int | None = None) -> int:
    rank_config = get_rank_query_config()
    configured_limit = max(0, rank_config.limit)
    requested_limit = configured_limit if search_limit is None else max(0, search_limit)
    return min(requested_limit, configured_limit)


async def _find_rank(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    title: str,
    score_name: str,
    key: int,
    sub_key: int,
    target_score: int | None = None,
    search_limit: int | None = None,
) -> RankLookupResult:
    score_target = (
        target_score if target_score is not None and target_score > 0 else None
    )
    limit = (
        _score_search_limit(search_limit)
        if score_target is not None
        else _online_search_limit(search_limit)
    )
    page_size = max(1, min(get_rank_query_config().page_size, 100))

    result = RankLookupResult(
        title=title,
        score_name=score_name,
        searched_limit=limit,
        queried=limit > 0,
    )

    cached_result = await _find_rank_by_cached_position(
        game,
        user_id=user_id,
        key=key,
        sub_key=sub_key,
        page_size=page_size,
        result=result,
    )
    if cached_result is not None:
        return cached_result

    if limit <= 0:
        return result

    if score_target is not None:
        return await _find_rank_by_score(
            game,
            user_id=user_id,
            key=key,
            sub_key=sub_key,
            target_score=score_target,
            limit=limit,
            page_size=page_size,
            result=result,
        )

    return await _find_rank_by_linear_scan(
        game,
        user_id=user_id,
        key=key,
        sub_key=sub_key,
        limit=limit,
        page_size=page_size,
        result=result,
    )


async def _find_pet_kind_rank(
    game: Any,
    *,
    user_id: int,
    pet_kind_count: int,
    search_limit: int,
) -> RankLookupResult:
    real_search_limit = _online_search_limit(search_limit)
    raw_search_limit = real_search_limit + PET_KIND_RANK_ANOMALY_COUNT
    result = RankLookupResult(
        title="精灵图鉴",
        score_name="精灵",
        score=pet_kind_count or None,
        searched_limit=real_search_limit,
        queried=real_search_limit > 0,
    )

    if is_pet_kind_rank_anomaly_user(user_id):
        result.rank = 0
        if result.score is None:
            result.score = 0
        return result

    cached_result = await _find_rank_by_cached_position(
        game,
        user_id=user_id,
        key=PET_KIND_RANK_KEY,
        sub_key=PET_KIND_RANK_SUB_KEY,
        page_size=max(1, min(get_rank_query_config().page_size, 100)),
        result=result,
    )
    if cached_result is not None:
        cached_result.searched_limit = real_search_limit
        if cached_result.rank is not None:
            cached_result.rank = max(
                0, cached_result.rank - PET_KIND_RANK_ANOMALY_COUNT
            )
        return cached_result

    if real_search_limit <= 0:
        return result

    raw_result = await _find_rank_by_linear_scan(
        game,
        user_id=user_id,
        key=PET_KIND_RANK_KEY,
        sub_key=PET_KIND_RANK_SUB_KEY,
        limit=raw_search_limit,
        page_size=max(1, min(get_rank_query_config().page_size, 100)),
        result=result,
    )
    raw_result.searched_limit = real_search_limit
    if raw_result.rank is not None:
        raw_result.rank = max(0, raw_result.rank - PET_KIND_RANK_ANOMALY_COUNT)
    return raw_result


async def _fetch_book_breakdown_summary(
    game: Any,
    user_id: int,
    *,
    pet_kind_count: int = 0,
    skin_score: int | None = None,
) -> BookBreakdownSummary:
    limit = min(
        max(0, get_rank_query_config().limit),
        BOOK_BREAKDOWN_SCAN_LIMIT,
    )
    pet_kind = await _find_pet_kind_rank(
        game,
        user_id=user_id,
        pet_kind_count=pet_kind_count,
        search_limit=limit,
    )
    skin = await _find_rank(
        game,
        user_id=user_id,
        title="皮肤图鉴",
        score_name="皮肤",
        key=SKIN_RANK_KEY,
        sub_key=SKIN_RANK_SUB_KEY,
        target_score=skin_score,
        search_limit=limit,
    )
    countermark = await _find_rank(
        game,
        user_id=user_id,
        title="刻印图鉴",
        score_name="刻印",
        key=COUNTERMARK_RANK_KEY,
        sub_key=COUNTERMARK_RANK_SUB_KEY,
        search_limit=limit,
    )
    outfit_suit = await _find_rank(
        game,
        user_id=user_id,
        title="套装图鉴",
        score_name="套装",
        key=OUTFIT_RANK_KEY,
        sub_key=OUTFIT_SUIT_RANK_SUB_KEY,
        search_limit=limit,
    )
    outfit_part = await _find_rank(
        game,
        user_id=user_id,
        title="部件图鉴",
        score_name="部件",
        key=OUTFIT_RANK_KEY,
        sub_key=OUTFIT_PART_RANK_SUB_KEY,
        search_limit=limit,
    )
    mount = await _find_rank(
        game,
        user_id=user_id,
        title="座驾图鉴",
        score_name="座驾",
        key=OUTFIT_RANK_KEY,
        sub_key=MOUNT_RANK_SUB_KEY,
        search_limit=limit,
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


async def fetch_peak_season_rank_summary(
    game: Any,
    user_id: int,
    *,
    standard_score: int | None = None,
    wild_score: int | None = None,
    expert_score: int | None = None,
) -> PeakSeasonRankSummary:
    sub_key = get_current_peak_sub_key()
    if sub_key is None:
        return PeakSeasonRankSummary.empty()

    summary = PeakSeasonRankSummary.empty()
    if standard_score is not None and standard_score > 0:
        summary.standard = await _find_rank(
            game,
            user_id=user_id,
            title="竞技赛季榜",
            score_name="段位分",
            key=STANDARD_PEAK_USER_RANK_KEY,
            sub_key=sub_key,
            target_score=standard_score,
        )
    if wild_score is not None and wild_score > 0:
        summary.wild = await _find_rank(
            game,
            user_id=user_id,
            title="狂野赛季榜",
            score_name="段位分",
            key=WILD_PEAK_USER_RANK_KEY,
            sub_key=sub_key,
            target_score=wild_score,
        )
    if expert_score is not None and expert_score > 0:
        summary.expert = await _find_rank(
            game,
            user_id=user_id,
            title="专家赛季榜",
            score_name="专家积分",
            key=EXPERT_PEAK_USER_RANK_KEY,
            sub_key=sub_key,
            target_score=expert_score,
        )
    return summary


async def fetch_autocard_rank_summary(
    game: Any,
    user_id: int,
) -> RankLookupResult:
    return await _find_rank(
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
) -> PlayerRankSummary:
    book = await _find_rank(
        game,
        user_id=user_id,
        title="图鉴积分",
        score_name="图鉴积分",
        key=BOOK_RANK_KEY,
        sub_key=BOOK_RANK_SUB_KEY,
        target_score=book_score,
    )
    achieve = await _find_rank(
        game,
        user_id=user_id,
        title="成就点数",
        score_name="成就点数",
        key=ACHIEVE_RANK_KEY,
        sub_key=ACHIEVE_RANK_SUB_KEY,
        target_score=achieve_score,
    )
    breakdown = await _fetch_book_breakdown_summary(
        game,
        user_id,
        pet_kind_count=pet_kind_count,
        skin_score=skin_score,
    )
    return PlayerRankSummary(book=book, achieve=achieve, breakdown=breakdown)


def build_peak_rating_score(rank: int, star: int) -> int | None:
    if rank <= 0 and star <= 0:
        return None
    return rank * 100000 + star
