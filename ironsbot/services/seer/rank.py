# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from nonebot import logger

from ironsbot.config import get_app_config
from ironsbot.config.models.seer import LocalRankConfig, RankQueryConfig
from ironsbot.plugins.headless_seer.command_id import COMMAND_ID
from ironsbot.plugins.headless_seer.packets.peak import DailyRankParam
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
from ironsbot.services.seer.rank_page_cache import (
    get_cached_rank_item,
    get_cached_rank_item_by_index,
    get_cached_rank_page_result,
    get_rank_page_cache_summary,
    save_rank_page,
)

BOOK_BREAKDOWN_SCAN_LIMIT = 2_000
CACHED_RANK_LOOKUP_WINDOW_PAGES = 2
DEFAULT_SCORE_SEARCH_PROBE_LIMIT = 32
DEFAULT_SCORE_SEARCH_TIE_PAGE_LIMIT = 5
_RANK_WINDOW_REFRESH_KEYS: set[tuple[int, int, int, int]] = set()
_RANK_WINDOW_REFRESH_TASKS: set[asyncio.Task[None]] = set()


def get_rank_query_config() -> RankQueryConfig:
    return get_app_config().seer.rank


def get_local_rank_config() -> LocalRankConfig:
    return get_app_config().seer.local_rank


def _rank_page_size() -> int:
    configured = int(get_rank_query_config().page_size)
    return max(1, min(configured, 100))


def _rank_page_start(index: int) -> int:
    page_size = _rank_page_size()
    return max(0, index) // page_size * page_size


def is_pet_kind_rank_anomaly_user(user_id: int) -> bool:
    return user_id in PET_KIND_RANK_ANOMALY_USER_IDS


@dataclass(slots=True)
class RankLookupResult:
    title: str
    score_name: str
    rank: int | None = None
    score: int | None = None
    searched_limit: int = 0
    queried: bool = False


@dataclass(slots=True)
class RankScoreSearchItem:
    id: int
    nick: str
    score: int
    rank_index: int


@dataclass(slots=True)
class RankScoreSearchResult:
    title: str
    score_name: str
    target_score: int
    searched_limit: int = 0
    queried: bool = False
    boundary_score: int | None = None
    start_rank: int | None = None
    end_rank: int | None = None
    total_count: int = 0
    scanned_count: int = 0
    truncated: bool = False
    fetched_at: float = 0.0
    items: list[RankScoreSearchItem] = field(default_factory=list)


@dataclass(slots=True)
class RankPageResult:
    items: list[Any]
    fetched_at: float


@dataclass(slots=True)
class BookBreakdownSummary:
    pet_kind_count: int = 0
    pet_kind: RankLookupResult | None = None
    skin: RankLookupResult | None = None
    countermark: RankLookupResult | None = None
    outfit_suit: RankLookupResult | None = None
    outfit_part: RankLookupResult | None = None
    mount: RankLookupResult | None = None

    @classmethod
    def empty(cls) -> "BookBreakdownSummary":
        return cls(
            pet_kind=RankLookupResult(title="精灵图鉴", score_name="精灵"),
            skin=RankLookupResult(title="皮肤图鉴", score_name="皮肤"),
            countermark=RankLookupResult(title="刻印图鉴", score_name="刻印"),
            outfit_suit=RankLookupResult(title="套装图鉴", score_name="套装"),
            outfit_part=RankLookupResult(title="部件图鉴", score_name="部件"),
            mount=RankLookupResult(title="座驾图鉴", score_name="座驾"),
        )

    @property
    def outfit_count(self) -> int | None:
        suit_score = None if self.outfit_suit is None else self.outfit_suit.score
        part_score = None if self.outfit_part is None else self.outfit_part.score
        if suit_score is None or part_score is None:
            return None
        return int(suit_score) + int(part_score)

    @property
    def unlocked_count(self) -> int | None:
        scores: tuple[int | None, ...] = (
            self.pet_kind_count,
            None if self.skin is None else self.skin.score,
            None if self.countermark is None else self.countermark.score,
            self.outfit_count,
            None if self.mount is None else self.mount.score,
        )
        present_scores = [score for score in scores if score is not None]
        if len(present_scores) != len(scores):
            return None
        return sum(present_scores)


@dataclass(slots=True)
class PlayerRankSummary:
    book: RankLookupResult
    achieve: RankLookupResult
    breakdown: BookBreakdownSummary

    @classmethod
    def empty(cls) -> "PlayerRankSummary":
        return cls(
            book=RankLookupResult(title="图鉴积分", score_name="图鉴积分"),
            achieve=RankLookupResult(title="成就点数", score_name="成就点数"),
            breakdown=BookBreakdownSummary.empty(),
        )


@dataclass(slots=True)
class PeakSeasonRankSummary:
    standard: RankLookupResult
    wild: RankLookupResult
    expert: RankLookupResult

    @classmethod
    def empty(cls) -> "PeakSeasonRankSummary":
        return cls(
            standard=RankLookupResult(title="竞技赛季榜", score_name="段位分"),
            wild=RankLookupResult(title="狂野赛季榜", score_name="段位分"),
            expert=RankLookupResult(title="专家赛季榜", score_name="专家积分"),
        )


async def _fetch_rank_page_result(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
    use_cache: bool = False,
) -> RankPageResult:
    if use_cache:
        cached_page = get_cached_rank_page_result(
            key=key,
            sub_key=sub_key,
            start=start,
            end=end,
        )
        if cached_page is not None:
            return RankPageResult(
                items=list(cached_page.items),
                fetched_at=cached_page.fetched_at,
            )

    _head, rank_list = await game.send_and_wait(
        COMMAND_ID.GET_DAILY_RANK_INFO,
        DailyRankParam(key=key, sub_key=sub_key, start=start, end=end),
        timeout=15.0,
    )
    fetched_at = time.time()
    items = list(rank_list.rank_list)
    save_rank_page(
        key=key,
        sub_key=sub_key,
        start=start,
        end=end,
        items=items,
        fetched_at=fetched_at,
    )
    return RankPageResult(items=items, fetched_at=fetched_at)


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
    page_start = center_index // page_size * page_size
    first_page_start = max(
        0,
        page_start - CACHED_RANK_LOOKUP_WINDOW_PAGES * page_size,
    )
    last_page_start = page_start + CACHED_RANK_LOOKUP_WINDOW_PAGES * page_size
    return list(range(first_page_start, last_page_start + 1, page_size))


async def _refresh_cached_rank_window(
    game: Any,
    *,
    key: int,
    sub_key: int,
    center_index: int,
    page_size: int,
) -> None:
    for start in _rank_window_page_starts(
        center_index=center_index,
        page_size=page_size,
    ):
        await _fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=start + page_size - 1,
            use_cache=False,
        )
        interval = get_local_rank_config().refresh_interval_seconds
        await asyncio.sleep(min(interval, 0.5))


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
    cached_item = get_cached_rank_item(key=key, sub_key=sub_key, user_id=user_id)
    if cached_item is None:
        return None

    result.queried = True
    for start in _rank_window_page_starts(
        center_index=cached_item.rank_index,
        page_size=page_size,
    ):
        items = await _fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=start + page_size - 1,
            use_cache=False,
        )
        for offset, item in enumerate(items):
            if item.id == user_id:
                result.rank = start + offset + 1
                result.score = item.score
                return result

        if len(items) < page_size and start > cached_item.rank_index:
            break

    return None


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

        from ironsbot.plugins.db_sync.manager import db_manager
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


class RankSearchBudgetExhaustedError(RuntimeError):
    pass


async def _find_last_existing_score_index(
    start_index: int,
    end_index: int,
    score_at: Callable[[int], Awaitable[int | None]],
) -> tuple[int | None, int | None]:
    if end_index <= start_index:
        return None, None

    boundary_index = end_index - 1
    boundary_score = await score_at(boundary_index)
    if boundary_score is not None:
        return boundary_index, boundary_score

    first_score = await score_at(start_index)
    if first_score is None:
        return None, None

    low = start_index
    high = boundary_index
    while low + 1 < high:
        mid = (low + high) // 2
        score = await score_at(mid)
        if score is None:
            high = mid
        else:
            low = mid

    return low, await score_at(low)


def _score_search_probe_limit(limit: int) -> int:
    configured = int(
        getattr(
            get_rank_query_config(),
            "score_search_probe_limit",
            DEFAULT_SCORE_SEARCH_PROBE_LIMIT,
        )
    )
    return max(1, min(configured, max(limit, 1)))


def _score_search_tie_page_limit() -> int:
    configured = int(
        getattr(
            get_rank_query_config(),
            "score_search_tie_page_limit",
            DEFAULT_SCORE_SEARCH_TIE_PAGE_LIMIT,
        )
    )
    return max(1, configured)


async def _find_rank_by_score(  # noqa: C901, PLR0911, PLR0912, PLR0913, PLR0915
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
    result.score = target_score
    remaining_probes = _score_search_probe_limit(limit)
    item_cache: dict[int, Any | None] = {}

    async def item_at(index: int) -> Any | None:
        nonlocal remaining_probes

        if index in item_cache:
            return item_cache[index]

        if remaining_probes <= 0:
            raise RankSearchBudgetExhaustedError

        remaining_probes -= 1
        item = await _fetch_rank_item(game, key=key, sub_key=sub_key, index=index)
        item_cache[index] = item
        return item

    async def score_at(index: int) -> int | None:
        item = await item_at(index)
        return None if item is None else item.score

    try:
        last_index, boundary_score = await _find_last_existing_score_index(
            0,
            limit,
            score_at,
        )
    except RankSearchBudgetExhaustedError:
        return result

    if last_index is None:
        return result

    search_end = last_index + 1
    result.searched_limit = min(result.searched_limit, search_end)
    if boundary_score is None or target_score < boundary_score:
        return result

    low = 0
    high = search_end
    try:
        while low < high:
            mid = (low + high) // 2
            score = await score_at(mid)
            if score is None or score <= target_score:
                high = mid
            else:
                low = mid + 1
    except RankSearchBudgetExhaustedError:
        return result

    first_same_or_lower = low
    if first_same_or_lower >= search_end:
        return result

    try:
        first_score = await score_at(first_same_or_lower)
    except RankSearchBudgetExhaustedError:
        return result
    if first_score != target_score:
        return result

    low = first_same_or_lower
    high = search_end
    tie_end = search_end
    try:
        while low < high:
            mid = (low + high) // 2
            score = await score_at(mid)
            if score is None or score < target_score:
                high = mid
            else:
                low = mid + 1
        tie_end = low
    except RankSearchBudgetExhaustedError:
        tie_end = min(
            search_end,
            first_same_or_lower + page_size * _score_search_tie_page_limit(),
        )

    tie_end = min(tie_end, search_end)
    start = first_same_or_lower
    remaining_tie_pages = _score_search_tie_page_limit()
    while start < tie_end and remaining_tie_pages > 0:
        end = min(start + page_size - 1, tie_end - 1)
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

        remaining_tie_pages -= 1
        start = end + 1

    return result


def _cached_score_candidate_page_starts(
    *,
    key: int,
    sub_key: int,
    target_score: int,
    start_index: int,
    end_index: int,
) -> list[int]:
    starts: list[int] = []
    for page in get_rank_page_cache_summary(key=key, sub_key=sub_key):
        if page.min_score is None or page.max_score is None:
            continue
        if page.end_index < start_index or page.start_index >= end_index:
            continue
        if int(page.min_score) <= target_score <= int(page.max_score):
            starts.append(_rank_page_start(max(start_index, page.start_index)))
    return sorted(set(starts))


async def _fetch_rank_score_segment_from_cached_candidates(  # noqa: C901, PLR0912, PLR0913, PLR0915
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
    if not candidate_starts:
        return None

    page_size = _rank_page_size()
    max_pages = _score_search_tie_page_limit()
    fetched_pages: dict[int, RankPageResult] = {}
    fetched_times: list[float] = []
    truncated = len(candidate_starts) > max_pages

    async def fetch_page(page_start: int) -> RankPageResult | None:
        page_start = _rank_page_start(page_start)
        if page_start < start_index or page_start >= end_index:
            return None
        if page_start in fetched_pages:
            return fetched_pages[page_start]
        if len(fetched_pages) >= max_pages:
            return None

        page_result = await _fetch_rank_page_result(
            game,
            key=key,
            sub_key=sub_key,
            start=page_start,
            end=page_start + page_size - 1,
            use_cache=False,
        )
        fetched_pages[page_start] = page_result
        fetched_times.append(page_result.fetched_at)
        return page_result

    for page_start in candidate_starts[:max_pages]:
        await fetch_page(page_start)

    def collect_matches() -> list[int]:
        indexes: list[int] = []
        for page_start, page_result in fetched_pages.items():
            for offset, item in enumerate(page_result.items):
                rank_index = page_start + offset
                if rank_index < start_index or rank_index >= end_index:
                    continue
                if int(item.score) == target_score:
                    indexes.append(rank_index)
        return sorted(set(indexes))

    matching_indexes = collect_matches()
    if not matching_indexes:
        return None

    while len(fetched_pages) < max_pages:
        first_index = matching_indexes[0]
        first_page_start = _rank_page_start(first_index)
        first_page = fetched_pages.get(first_page_start)
        if first_page_start <= start_index or first_page is None:
            break
        if first_index != first_page_start:
            break
        previous_page = await fetch_page(first_page_start - page_size)
        if previous_page is None:
            truncated = True
            break
        matching_indexes = collect_matches()
        if matching_indexes[0] >= first_index:
            break

    while len(fetched_pages) < max_pages:
        last_index = matching_indexes[-1]
        last_page_start = _rank_page_start(last_index)
        last_page = fetched_pages.get(last_page_start)
        if last_page is None or not last_page.items:
            break
        page_last_index = last_page_start + len(last_page.items) - 1
        if last_index != page_last_index or len(last_page.items) < page_size:
            break
        next_page = await fetch_page(last_page_start + page_size)
        if next_page is None:
            truncated = True
            break
        matching_indexes = collect_matches()
        if matching_indexes[-1] <= last_index:
            break

    if not matching_indexes:
        return None

    matching_set = set(matching_indexes)
    first_index = matching_indexes[0]
    last_index = matching_indexes[-1]
    result.start_rank = first_index + 1 + rank_offset
    result.end_rank = last_index + 1 + rank_offset
    result.total_count = len(matching_indexes)
    result.truncated = truncated

    for page_start in sorted(fetched_pages):
        page_result = fetched_pages[page_start]
        for offset, item in enumerate(page_result.items):
            rank_index = page_start + offset
            if rank_index not in matching_set:
                continue
            result.items.append(
                RankScoreSearchItem(
                    id=int(item.id),
                    nick=str(item.nick),
                    score=int(item.score),
                    rank_index=rank_index,
                )
            )

    result.scanned_count = len(result.items)
    result.fetched_at = max(fetched_times, default=time.time())
    return result


async def fetch_rank_score_segment(  # noqa: C901, PLR0911, PLR0912, PLR0913, PLR0915
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
    limit = _score_search_limit(search_limit)
    result = RankScoreSearchResult(
        title=title,
        score_name=score_name,
        target_score=target_score,
        searched_limit=limit,
        queried=limit > 0,
    )
    if target_score <= 0 or limit <= 0:
        return result

    start_index = max(0, start_index)
    end_index = start_index + limit
    page_size = _rank_page_size()
    cached_result = await _fetch_rank_score_segment_from_cached_candidates(
        game,
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_offset=rank_offset,
        result=result,
        candidate_starts=_cached_score_candidate_page_starts(
            key=key,
            sub_key=sub_key,
            target_score=target_score,
            start_index=start_index,
            end_index=end_index,
        ),
    )
    if cached_result is not None:
        return cached_result

    remaining_probes = _score_search_probe_limit(limit)
    item_cache: dict[int, Any | None] = {}

    async def item_at(index: int) -> Any | None:
        nonlocal remaining_probes

        if index in item_cache:
            return item_cache[index]

        if remaining_probes <= 0:
            raise RankSearchBudgetExhaustedError

        remaining_probes -= 1
        item = await _fetch_rank_item(
            game,
            key=key,
            sub_key=sub_key,
            index=index,
            use_cache=False,
        )
        item_cache[index] = item
        return item

    async def score_at(index: int) -> int | None:
        item = await item_at(index)
        return None if item is None else int(item.score)

    try:
        last_index, boundary_score = await _find_last_existing_score_index(
            start_index,
            end_index,
            score_at,
        )
    except RankSearchBudgetExhaustedError:
        return result

    result.boundary_score = boundary_score
    if last_index is None:
        return result

    end_index = last_index + 1
    result.searched_limit = min(result.searched_limit, end_index - start_index)
    if boundary_score is None or target_score < boundary_score:
        return result

    low = start_index
    high = end_index
    try:
        while low < high:
            mid = (low + high) // 2
            score = await score_at(mid)
            if score is None or score <= target_score:
                high = mid
            else:
                low = mid + 1
    except RankSearchBudgetExhaustedError:
        return result

    first_same_or_lower = low
    if first_same_or_lower >= end_index:
        return result

    try:
        first_score = await score_at(first_same_or_lower)
    except RankSearchBudgetExhaustedError:
        return result
    if first_score != target_score:
        return result

    low = first_same_or_lower
    high = end_index
    tie_end = end_index
    try:
        while low < high:
            mid = (low + high) // 2
            score = await score_at(mid)
            if score is None or score < target_score:
                high = mid
            else:
                low = mid + 1
        tie_end = low
    except RankSearchBudgetExhaustedError:
        tie_end = min(
            end_index,
            first_same_or_lower + page_size * _score_search_tie_page_limit(),
        )
        result.truncated = True

    tie_end = min(tie_end, end_index)
    result.start_rank = first_same_or_lower + 1 + rank_offset
    result.end_rank = tie_end + rank_offset
    result.total_count = max(0, tie_end - first_same_or_lower)

    first_page_start = _rank_page_start(first_same_or_lower)
    last_page_start = _rank_page_start(max(first_same_or_lower, tie_end - 1))
    max_pages = _score_search_tie_page_limit()
    fetched_pages = 0
    fetched_times: list[float] = []

    for page_start in range(first_page_start, last_page_start + 1, page_size):
        if fetched_pages >= max_pages:
            result.truncated = True
            break

        page_result = await _fetch_rank_page_result(
            game,
            key=key,
            sub_key=sub_key,
            start=page_start,
            end=page_start + page_size - 1,
            use_cache=False,
        )
        fetched_times.append(page_result.fetched_at)
        fetched_pages += 1

        for offset, item in enumerate(page_result.items):
            rank_index = page_start + offset
            if rank_index < first_same_or_lower or rank_index >= tie_end:
                continue
            if int(item.score) != target_score:
                continue
            result.items.append(
                RankScoreSearchItem(
                    id=int(item.id),
                    nick=str(item.nick),
                    score=int(item.score),
                    rank_index=rank_index,
                )
            )

        if len(page_result.items) < page_size:
            break

    result.scanned_count = len(result.items)
    result.fetched_at = max(fetched_times, default=time.time())
    return result


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
    has_target_score = target_score is not None and target_score > 0
    limit = (
        _score_search_limit(search_limit)
        if has_target_score
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

    if has_target_score:
        return await _find_rank_by_score(
            game,
            user_id=user_id,
            key=key,
            sub_key=sub_key,
            target_score=target_score,
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


def format_rank_lookup(result: RankLookupResult) -> str:
    if not result.queried:
        return f"{result.title}：未查询"

    if result.rank is None:
        suffix = (
            ""
            if result.score is None
            else f"（{result.score_name}：{result.score}）"
        )
        return f"{result.title}：前 {result.searched_limit} 名未上榜{suffix}"

    return f"{result.title}：第 {result.rank} 名（{result.score_name}：{result.score}）"


def format_peak_rank_lookup(result: RankLookupResult, *, inactive_text: str) -> str:
    if not result.queried and result.score is None:
        return inactive_text
    if not result.queried:
        return "未查询"
    if result.rank is None:
        return f"前 {result.searched_limit} 名未上榜"
    return f"第 {result.rank} 名"


def _format_score_rank(result: RankLookupResult | None) -> str:
    if result is None or not result.queried:
        return "未查询"

    if result.score is None:
        return f"前 {result.searched_limit} 名未上榜"

    if result.rank is None:
        return f"{result.score}（前 {result.searched_limit} 名未上榜）"

    return f"{result.score}（第 {result.rank} 名）"


def build_peak_rating_score(rank: int, star: int) -> int | None:
    if rank <= 0 and star <= 0:
        return None
    return rank * 100000 + star


def format_book_breakdown(summary: BookBreakdownSummary) -> str:
    outfit_count = summary.outfit_count
    outfit_text = "未知"
    if outfit_count is not None:
        outfit_text = (
            f"{outfit_count}"
            f"（套装 {_format_score_rank(summary.outfit_suit)}；"
            f"部件 {_format_score_rank(summary.outfit_part)}；未找到合并总榜）"
        )

    unlocked_count = summary.unlocked_count
    unlocked_line = (
        "已解锁图鉴条目：未知"
        if unlocked_count is None
        else f"已解锁图鉴条目：{unlocked_count}"
    )

    return "\n".join(
        (
            "【图鉴条目拆分】",
            f"精灵图鉴：{_format_score_rank(summary.pet_kind)}",
            f"皮肤图鉴：{_format_score_rank(summary.skin)}",
            f"装扮图鉴：{outfit_text}",
            f"座驾图鉴：{_format_score_rank(summary.mount)}",
            f"刻印图鉴：{_format_score_rank(summary.countermark)}",
            unlocked_line,
        )
    )


def format_player_rank_summary(summary: PlayerRankSummary) -> str:
    return "\n".join(
        (
            "【全服排行】",
            format_rank_lookup(summary.book),
            format_rank_lookup(summary.achieve),
            "",
            format_book_breakdown(summary.breakdown),
        )
    )
