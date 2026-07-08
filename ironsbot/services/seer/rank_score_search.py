# SPDX-License-Identifier: GPL-3.0-or-later
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ironsbot.config.models.seer import RankQueryConfig
from ironsbot.services.seer.rank_models import (
    RankLookupResult,
    RankPageResult,
    RankScoreMissProof,
    RankScoreSearchItem,
    RankScoreSearchResult,
)

DEFAULT_SCORE_SEARCH_PROBE_LIMIT = 32
DEFAULT_SCORE_SEARCH_TIE_PAGE_LIMIT = 5


class RankSearchBudgetExhaustedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RankScoreSegmentDependencies:
    score_search_limit: Callable[[int | None], int]
    rank_page_size: Callable[[], int]
    rank_page_start: Callable[[int], int]
    cached_score_miss_boundary: Callable[..., RankScoreMissProof | None]
    cached_score_candidate_page_starts: Callable[..., list[int]]
    fetch_cached_candidates: Callable[..., Awaitable[RankScoreSearchResult | None]]
    score_search_probe_limit: Callable[[int], int]
    score_search_tie_page_limit: Callable[[], int]
    find_last_existing_score_index: Callable[
        [int, int, Callable[[int], Awaitable[int | None]]],
        Awaitable[tuple[int | None, int | None]],
    ]
    fetch_rank_item: Callable[..., Awaitable[Any | None]]
    fetch_rank_page_result: Callable[..., Awaitable[RankPageResult]]
    score_miss_proof_from_page: Callable[..., RankScoreMissProof | None]


async def find_last_existing_score_index(
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


def score_search_probe_limit(config: RankQueryConfig, limit: int) -> int:
    configured = int(
        getattr(config, "score_search_probe_limit", DEFAULT_SCORE_SEARCH_PROBE_LIMIT)
    )
    return max(1, min(configured, max(limit, 1)))


def score_search_tie_page_limit(config: RankQueryConfig) -> int:
    configured = int(
        getattr(
            config,
            "score_search_tie_page_limit",
            DEFAULT_SCORE_SEARCH_TIE_PAGE_LIMIT,
        )
    )
    return max(1, configured)


async def find_rank_by_score(  # noqa: C901, PLR0911, PLR0912, PLR0913, PLR0915
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    target_score: int,
    limit: int,
    page_size: int,
    result: RankLookupResult,
    score_search_probe_limit: Callable[[int], int],
    score_search_tie_page_limit: Callable[[], int],
    find_last_existing_score_index: Callable[
        [int, int, Callable[[int], Awaitable[int | None]]],
        Awaitable[tuple[int | None, int | None]],
    ],
    fetch_rank_item: Callable[..., Awaitable[Any | None]],
    fetch_rank_page: Callable[..., Awaitable[list[Any]]],
) -> RankLookupResult:
    result.score = target_score
    remaining_probes = score_search_probe_limit(limit)
    item_cache: dict[int, Any | None] = {}

    async def item_at(index: int) -> Any | None:
        nonlocal remaining_probes

        if index in item_cache:
            return item_cache[index]

        if remaining_probes <= 0:
            raise RankSearchBudgetExhaustedError

        remaining_probes -= 1
        item = await fetch_rank_item(game, key=key, sub_key=sub_key, index=index)
        item_cache[index] = item
        return item

    async def score_at(index: int) -> int | None:
        item = await item_at(index)
        return None if item is None else item.score

    try:
        last_index, boundary_score = await find_last_existing_score_index(
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
            first_same_or_lower + page_size * score_search_tie_page_limit(),
        )

    tie_end = min(tie_end, search_end)
    start = first_same_or_lower
    remaining_tie_pages = score_search_tie_page_limit()
    while start < tie_end and remaining_tie_pages > 0:
        end = min(start + page_size - 1, tie_end - 1)
        items = await fetch_rank_page(
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


async def _populate_score_miss_proof_from_online_page(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    target_score: int,
    gap_index: int,
    rank_offset: int,
    result: RankScoreSearchResult,
    deps: RankScoreSegmentDependencies,
) -> None:
    page_size = deps.rank_page_size()
    page_start = deps.rank_page_start(gap_index)
    proof_page_start = page_start
    page_result = await deps.fetch_rank_page_result(
        game,
        key=key,
        sub_key=sub_key,
        start=page_start,
        end=page_start + page_size - 1,
        use_cache=False,
    )
    proof_items = page_result.items
    fetched_at = page_result.fetched_at
    if page_start > 0 and gap_index == page_start:
        previous_page_start = page_start - page_size
        previous_page_result = await deps.fetch_rank_page_result(
            game,
            key=key,
            sub_key=sub_key,
            start=previous_page_start,
            end=previous_page_start + page_size - 1,
            use_cache=False,
        )
        proof_page_start = previous_page_start
        proof_items = [*previous_page_result.items, *page_result.items]
        fetched_at = max(previous_page_result.fetched_at, page_result.fetched_at)
    proof = deps.score_miss_proof_from_page(
        items=proof_items,
        page_start=proof_page_start,
        target_score=target_score,
        rank_offset=rank_offset,
        fetched_at=fetched_at,
    )
    if proof is None:
        return
    result.boundary_score = proof.boundary_score
    result.fetched_at = proof.fetched_at
    result.higher_gap = proof.higher_gap
    result.lower_gap = proof.lower_gap


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
    deps: RankScoreSegmentDependencies,
) -> RankScoreSearchResult:
    limit = deps.score_search_limit(search_limit)
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
    page_size = deps.rank_page_size()
    cached_miss = deps.cached_score_miss_boundary(
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_offset=rank_offset,
    )
    if cached_miss is not None:
        result.boundary_score = cached_miss.boundary_score
        result.fetched_at = cached_miss.fetched_at
        result.higher_gap = cached_miss.higher_gap
        result.lower_gap = cached_miss.lower_gap
        return result

    cached_result = await deps.fetch_cached_candidates(
        game,
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_offset=rank_offset,
        result=result,
        candidate_starts=deps.cached_score_candidate_page_starts(
            key=key,
            sub_key=sub_key,
            target_score=target_score,
            start_index=start_index,
            end_index=end_index,
        ),
    )
    if cached_result is not None:
        return cached_result

    remaining_probes = deps.score_search_probe_limit(limit)
    item_cache: dict[int, Any | None] = {}

    async def item_at(index: int) -> Any | None:
        nonlocal remaining_probes

        if index in item_cache:
            return item_cache[index]

        if remaining_probes <= 0:
            raise RankSearchBudgetExhaustedError

        remaining_probes -= 1
        item = await deps.fetch_rank_item(
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
        last_index, boundary_score = await deps.find_last_existing_score_index(
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
        await _populate_score_miss_proof_from_online_page(
            game,
            key=key,
            sub_key=sub_key,
            target_score=target_score,
            gap_index=first_same_or_lower,
            rank_offset=rank_offset,
            result=result,
            deps=deps,
        )
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
            first_same_or_lower + page_size * deps.score_search_tie_page_limit(),
        )
        result.truncated = True

    tie_end = min(tie_end, end_index)
    result.start_rank = first_same_or_lower + 1 + rank_offset
    result.end_rank = tie_end + rank_offset
    result.total_count = max(0, tie_end - first_same_or_lower)

    first_page_start = deps.rank_page_start(first_same_or_lower)
    last_page_start = deps.rank_page_start(max(first_same_or_lower, tie_end - 1))
    max_pages = deps.score_search_tie_page_limit()
    fetched_pages = 0
    fetched_times: list[float] = []

    for page_start in range(first_page_start, last_page_start + 1, page_size):
        if fetched_pages >= max_pages:
            result.truncated = True
            break

        page_result = await deps.fetch_rank_page_result(
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


__all__ = [
    "DEFAULT_SCORE_SEARCH_PROBE_LIMIT",
    "DEFAULT_SCORE_SEARCH_TIE_PAGE_LIMIT",
    "RankScoreSegmentDependencies",
    "RankSearchBudgetExhaustedError",
    "fetch_rank_score_segment",
    "find_last_existing_score_index",
    "find_rank_by_score",
    "score_search_probe_limit",
    "score_search_tie_page_limit",
]
