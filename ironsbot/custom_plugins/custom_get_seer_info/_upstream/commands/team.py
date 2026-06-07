# SPDX-License-Identifier: GPL-3.0-or-later
from typing import NoReturn

from nonebot.matcher import Matcher
from nonebot.typing import T_State

from ironsbot.plugins.headless_seer.game import SeerGame
from ironsbot.plugins.headless_seer.packets.team import SimpleTeamInfo
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..depends import GameClient
from ..depends.arg_validator import TeamIdArg
from ..group import matcher_group

team_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(prefixes=("战队", "查询战队信息"), suffixes=())
    & no_reply()
)


def _format_team_info(info: SimpleTeamInfo) -> str:
    name = info.name
    slogan = info.slogan or "（无）"
    notice = info.notice or "（无）"
    return (
        f"🏰【{name}】\n"
        f"战队ID：{info.team_id}\n"
        f"等级：{info.new_team_level}\n"
        f"队长：{info.leader}（米米号）\n"
        f"成员数：{info.member_count}\n"
        f"战队资源：{info.score}\n"
        f"标语：{slogan}\n"
        f"公告：{notice}"
    )


TEAM_ID_KEY = "team_id"


@team_matcher.handle()
async def validate_team_id(
    state: T_State,
    team_id: int = TeamIdArg,
) -> None:
    state[TEAM_ID_KEY] = team_id


@team_matcher.handle()
async def handle_team(
    matcher: Matcher,
    state: T_State,
    game: SeerGame = GameClient,
) -> NoReturn:
    team_id: int = state[TEAM_ID_KEY]
    team_info = await game.get_team_info(team_id)

    await matcher.finish(_format_team_info(team_info))
