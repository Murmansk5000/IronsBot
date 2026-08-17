# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from ironsbot.services.seer.rank_models import RankLookupResult, RankPageResult


def restore_cached_rank_after_timeout(
    result: RankLookupResult,
    cached_item: Any,
) -> RankLookupResult:
    """Keep the last observed rank visible when live confirmation times out."""

    result.rank = int(cached_item.rank_index) + 1
    result.score = int(cached_item.score)
    result.failure = "查询超时"
    result.fallback_cached_at = float(cached_item.fetched_at)
    return result


async def find_rank_by_cached_position(  # noqa: C901, PLR0913
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    page_size: int,
    result: RankLookupResult,
    get_cached_rank_item: Callable[..., Any | None],
    rank_window_page_starts: Callable[..., list[int]],
    fetch_rank_page: Callable[..., Awaitable[RankPageResult]],
    fetch_rank_pages: Callable[..., Awaitable[list[RankPageResult]]] | None = None,
    anchor_only: bool = False,
    parallelism: int = 1,
) -> RankLookupResult | None:
    cached_item = get_cached_rank_item(key=key, sub_key=sub_key, user_id=user_id)
    if cached_item is None:
        return None

    result.cost.anchor_page_start = (
        cached_item.rank_index // page_size * page_size
    )
    starts = rank_window_page_starts(
        center_index=cached_item.rank_index,
        page_size=page_size,
    )

    async def inspect(start: int, page: RankPageResult, *, index: int) -> bool:
        result.queried = True
        result.cost.page_starts.append(start)
        if page.from_cache:
            result.cost.cache_page_hits += 1
        else:
            result.cost.online_page_fetches += 1
        for offset, item in enumerate(page.items):
            if item.id == user_id:
                result.rank = start + offset + 1
                result.score = item.score
                result.cost.anchor_page_hit = index == 0
                return True
        return False

    anchor_start = starts[0]
    page = await fetch_rank_page(
        game,
        key=key,
        sub_key=sub_key,
        start=anchor_start,
        end=anchor_start + page_size - 1,
        use_cache=False,
    )
    if await inspect(anchor_start, page, index=0):
        return result
    if anchor_only:
        result.cost.restricted_miss = True
        return result

    remaining_starts = starts[1:]
    for offset in range(0, len(remaining_starts), max(1, parallelism)):
        batch_starts = tuple(remaining_starts[offset : offset + max(1, parallelism)])
        result.cost.expanded = True
        if fetch_rank_pages is None:
            pages = await asyncio.gather(
                *(
                    fetch_rank_page(
                        game,
                        key=key,
                        sub_key=sub_key,
                        start=start,
                        end=start + page_size - 1,
                        use_cache=False,
                        parallel=True,
                    )
                    for start in batch_starts
                )
            )
        else:
            pages = await fetch_rank_pages(
                game,
                key=key,
                sub_key=sub_key,
                starts=batch_starts,
                use_cache=False,
            )
        for index, (start, page) in enumerate(
            zip(batch_starts, pages, strict=True),
            start=offset + 1,
        ):
            if await inspect(start, page, index=index):
                return result
            if len(page.items) < page_size and start > cached_item.rank_index:
                return None

    return None
