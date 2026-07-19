# SPDX-License-Identifier: GPL-3.0-or-later
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
    _head, rank_list = await game.send_and_wait(
        COMMAND_ID.GET_DAILY_RANK_INFO,
        DailyRankParam(key=key, sub_key=sub_key, start=start, end=end),
        timeout=15.0,
    )
    return [
        RankEntry(id=item.id, nick=item.nick, score=item.score)
        for item in rank_list.rank_list
    ]
