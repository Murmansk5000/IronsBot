# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.config.loader import get_app_config
from ironsbot.services.seer.rank_fetching import fetch_rank_page_result_from_game
from ironsbot.services.seer.rank_page_cache import (
    get_cached_rank_item_by_index,
    get_cached_rank_page_result,
    save_rank_page,
)
from ironsbot.services.seer.rank_pagination import (
    rank_page_size as _rank_page_size,
)
from ironsbot.services.seer.rank_pagination import (
    rank_page_start as _rank_page_start,
)
from ironsbot.services.seer.rank_range import (
    fetch_rank_range,
    fetch_rank_range_result,
)

if TYPE_CHECKING:
    from ironsbot.config.models.seer import RankQueryConfig
    from ironsbot.services.seer.rank_models import RankPageResult


def get_rank_query_config() -> RankQueryConfig:
    return get_app_config().seer.rank


def rank_page_size() -> int:
    return _rank_page_size(get_rank_query_config())


def rank_page_start(index: int) -> int:
    return _rank_page_start(index, page_size=rank_page_size())


async def fetch_rank_page_result(  # noqa: PLR0913
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


async def fetch_rank_page(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
    use_cache: bool = False,
) -> list[Any]:
    result = await fetch_rank_page_result(
        game,
        key=key,
        sub_key=sub_key,
        start=start,
        end=end,
        use_cache=use_cache,
    )
    return result.items


async def fetch_rank_item(
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

    page_size = rank_page_size()
    page_start = rank_page_start(index)
    items = await fetch_rank_page(
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
    return await fetch_rank_range(
        game,
        key=key,
        sub_key=sub_key,
        start=start,
        count=count,
        use_cache=use_cache,
        rank_page_size=rank_page_size,
        fetch_rank_page_result=fetch_rank_page_result,
    )


async def fetch_daily_rank_page_result(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    count: int,
    use_cache: bool = False,
) -> RankPageResult:
    return await fetch_rank_range_result(
        game,
        key=key,
        sub_key=sub_key,
        start=start,
        count=count,
        use_cache=use_cache,
        rank_page_size=rank_page_size,
        fetch_rank_page_result=fetch_rank_page_result,
    )
