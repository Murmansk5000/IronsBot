# SPDX-License-Identifier: GPL-3.0-or-later
from ironsbot.core.rank_lookup_context import rank_page_request_timeout
from ironsbot.integrations.headless_seer.command_id import COMMAND_ID
from ironsbot.integrations.headless_seer.game import SeerGame
from ironsbot.integrations.headless_seer.packets.peak import DailyRankParam
from ironsbot.integrations.headless_seer.type_hint import CommandID
from ironsbot.services.seer.rank_models import RankEntry
from ironsbot.services.seer.somua import (
    SOMUA_RANK_COMMAND,
    SOMUA_RANK_KEY,
    SOMUA_RANK_LIMIT,
    SOMUA_RANK_PAGE_SIZE,
    SOMUA_RANK_SUB_KEY,
    parse_somua_rank_page,
)


async def fetch_rank_page(
    game: SeerGame,
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
) -> list[RankEntry]:
    timeout = rank_page_request_timeout.get() or 15.0
    if key == SOMUA_RANK_KEY:
        if sub_key != SOMUA_RANK_SUB_KEY or start < 0 or end < start:
            raise ValueError("苏摩榜单查询范围异常")
        end = min(end, SOMUA_RANK_LIMIT - 1)
        items: list[RankEntry] = []
        for offset in range(start, end + 1, SOMUA_RANK_PAGE_SIZE):
            last = min(offset + SOMUA_RANK_PAGE_SIZE - 1, end)
            _head, body = await game.send_and_wait(
                CommandID(SOMUA_RANK_COMMAND), 1, offset, last, timeout=timeout
            )
            page = parse_somua_rank_page(bytes(body), last - offset + 1)
            items.extend(page)
            if len(page) < last - offset + 1:
                break
        return items
    _head, rank_list = await game.send_and_wait(
        COMMAND_ID.GET_DAILY_RANK_INFO,
        DailyRankParam(key=key, sub_key=sub_key, start=start, end=end),
        timeout=timeout,
    )
    return [
        RankEntry(id=item.id, nick=item.nick, score=item.score)
        for item in rank_list.rank_list
    ]
