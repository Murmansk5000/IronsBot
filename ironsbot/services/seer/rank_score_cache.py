# SPDX-License-Identifier: GPL-3.0-or-later
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from ironsbot.services.seer.rank_models import (
    RankPageResult,
    RankScoreSearchItem,
    RankScoreSearchResult,
)
from ironsbot.services.seer.rank_score_helpers import score_segment_sample_indexes


def cached_score_candidate_page_starts(  # noqa: PLR0913
    *,
    key: int,
    sub_key: int,
    target_score: int,
    start_index: int,
    end_index: int,
    rank_page_start: Callable[[int], int],
    get_cached_score_indexes: Callable[..., Sequence[int]],
    get_cache_summary: Callable[..., Sequence[Any]],
) -> list[int]:
    starts: list[int] = []
    starts.extend(
        rank_page_start(index)
        for index in get_cached_score_indexes(
            key=key,
            sub_key=sub_key,
            score=target_score,
            start_index=start_index,
            end_index=end_index,
        )
    )
    for page in get_cache_summary(key=key, sub_key=sub_key):
        if page.min_score is None or page.max_score is None:
            continue
        if page.end_index < start_index or page.start_index >= end_index:
            continue
        if int(page.min_score) <= target_score <= int(page.max_score):
            starts.append(rank_page_start(max(start_index, page.start_index)))
    return sorted(set(starts))


async def fetch_rank_score_segment_from_cached_candidates(  # noqa: C901, PLR0912, PLR0913, PLR0915
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
    sample_limit: int | None,
    rank_page_size: Callable[[], int],
    rank_page_start: Callable[[int], int],
    score_search_tie_page_limit: Callable[[], int],
    fetch_rank_page_result: Callable[..., Awaitable[RankPageResult]],
) -> RankScoreSearchResult | None:
    if not candidate_starts:
        return None

    page_size = rank_page_size()
    max_pages = score_search_tie_page_limit()
    if len(candidate_starts) > max_pages:
        return None

    fetched_pages: dict[int, RankPageResult] = {}
    fetched_times: list[float] = []
    truncated = False

    async def fetch_page(page_start: int) -> RankPageResult | None:
        page_start = rank_page_start(page_start)
        if page_start < start_index or page_start >= end_index:
            return None
        if page_start in fetched_pages:
            return fetched_pages[page_start]
        if len(fetched_pages) >= max_pages:
            return None

        page_result = await fetch_rank_page_result(
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
        first_page_start = rank_page_start(first_index)
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
        last_page_start = rank_page_start(last_index)
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
    if truncated:
        return None

    first_index = matching_indexes[0]
    last_index = matching_indexes[-1]
    sample_indexes = score_segment_sample_indexes(
        first_index,
        last_index + 1,
        sample_limit,
    )
    matching_set = (
        set(matching_indexes)
        if sample_indexes is None
        else set(matching_indexes).intersection(sample_indexes)
    )
    result.start_rank = first_index + 1 + rank_offset
    result.end_rank = last_index + 1 + rank_offset
    result.total_count = len(matching_indexes)
    result.truncated = False

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
