# SPDX-License-Identifier: GPL-3.0-or-later
import time
from collections.abc import Callable
from typing import Any

from ironsbot.integrations.headless_seer.command_id import COMMAND_ID
from ironsbot.integrations.headless_seer.packets.peak import DailyRankParam
from ironsbot.services.seer.rank_models import RankPageResult


async def fetch_rank_page_result_from_game(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
    use_cache: bool,
    get_cached_page: Callable[..., Any],
    save_page: Callable[..., object],
) -> RankPageResult:
    if use_cache:
        cached_page = get_cached_page(
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
    save_page(
        key=key,
        sub_key=sub_key,
        start=start,
        end=end,
        items=items,
        fetched_at=fetched_at,
    )
    return RankPageResult(items=items, fetched_at=fetched_at)
