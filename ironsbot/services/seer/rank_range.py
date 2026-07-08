# SPDX-License-Identifier: GPL-3.0-or-later
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ironsbot.services.seer.rank_models import RankPageResult


async def fetch_rank_range_result(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    count: int,
    use_cache: bool,
    rank_page_size: Callable[[], int],
    fetch_rank_page_result: Callable[..., Awaitable[RankPageResult]],
) -> RankPageResult:
    if count <= 0:
        return RankPageResult(items=[], fetched_at=time.time())

    request_start = max(0, start)
    request_end = request_start + count - 1
    page_size = rank_page_size()
    first_page_start = request_start // page_size * page_size
    last_page_start = request_end // page_size * page_size
    items: list[Any] = []
    fetched_times: list[float] = []

    for page_start in range(first_page_start, last_page_start + 1, page_size):
        page_result = await fetch_rank_page_result(
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


async def fetch_rank_range(
    game: Any,
    **kwargs: Any,
) -> list[Any]:
    if int(kwargs.get("count", 0)) <= 0:
        return []

    result = await fetch_rank_range_result(game, **kwargs)
    return result.items


__all__ = [
    "fetch_rank_range",
    "fetch_rank_range_result",
]
