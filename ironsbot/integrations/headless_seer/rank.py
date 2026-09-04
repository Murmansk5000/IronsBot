# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import time

from ironsbot.core.rank_lookup_context import rank_page_request_timeout, rank_query_id
from ironsbot.integrations.headless_seer.command_id import COMMAND_ID
from ironsbot.integrations.headless_seer.game import SeerGame
from ironsbot.integrations.headless_seer.packets.peak import DailyRankParam
from ironsbot.services.seer.rank_models import RankEntry


async def fetch_rank_page(
    game: SeerGame,
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
) -> list[RankEntry]:
    timeout = rank_page_request_timeout.get() or 15.0
    started = time.monotonic()
    _head, rank_list = await game.send_and_wait(
        COMMAND_ID.GET_DAILY_RANK_INFO,
        DailyRankParam(key=key, sub_key=sub_key, start=start, end=end),
        timeout=timeout,
    )
    logging.getLogger(__name__).info(
        "rank decoded response query=%s worker=%s key=%s sub_key=%s "
        "range=%s-%s elapsed=%.3fs count=%s",
        rank_query_id.get(),
        getattr(_head, "user_id", None),
        key,
        sub_key,
        start,
        end,
        time.monotonic() - started,
        len(rank_list.rank_list),
    )
    return [
        RankEntry(id=item.id, nick=item.nick, score=item.score)
        for item in rank_list.rank_list
    ]
