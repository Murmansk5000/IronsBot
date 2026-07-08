# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from ironsbot.services.seer.rank_models import RankLookupResult


async def refresh_cached_rank_window(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    center_index: int,
    page_size: int,
    rank_window_page_starts: Callable[..., list[int]],
    fetch_rank_page: Callable[..., Awaitable[list[Any]]],
    refresh_interval_seconds: float,
) -> None:
    for start in rank_window_page_starts(
        center_index=center_index,
        page_size=page_size,
    ):
        await fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=start + page_size - 1,
            use_cache=False,
        )
        await asyncio.sleep(min(refresh_interval_seconds, 0.5))


async def find_rank_by_cached_position(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    page_size: int,
    result: RankLookupResult,
    get_cached_rank_item: Callable[..., Any | None],
    rank_window_page_starts: Callable[..., list[int]],
    fetch_rank_page: Callable[..., Awaitable[list[Any]]],
) -> RankLookupResult | None:
    cached_item = get_cached_rank_item(key=key, sub_key=sub_key, user_id=user_id)
    if cached_item is None:
        return None

    result.queried = True
    for start in rank_window_page_starts(
        center_index=cached_item.rank_index,
        page_size=page_size,
    ):
        items = await fetch_rank_page(
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


__all__ = [
    "find_rank_by_cached_position",
    "refresh_cached_rank_window",
]
