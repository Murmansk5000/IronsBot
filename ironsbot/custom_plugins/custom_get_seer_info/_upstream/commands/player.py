# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from datetime import datetime, timedelta, timezone
from typing import NoReturn

from nonebot.matcher import Matcher
from nonebot.typing import T_State

from ironsbot.plugins.headless_seer.exception import SocketRecvError
from ironsbot.plugins.headless_seer.game import PeakData, SeerGame
from ironsbot.plugins.headless_seer.packets.user import MoreInfo, UserInfo
from ironsbot.plugins.headless_seer.utils import split_bits
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..depends import GameClient
from ..depends.arg_validator import PlayerIdArg
from ..group import matcher_group

player_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(prefixes=("查询玩家信息", "米米号"), suffixes=())
    & no_reply()
)

PEAK_RATING_NAMES = ("学徒", "猛将", "天骄", "王者", "圣皇", "宇宙圣皇")


def _format_peak_rating(data: int) -> str:
    _, rank = split_bits(data, 16, 16)
    if rank >= len(PEAK_RATING_NAMES):
        return "未知"
    return f"{PEAK_RATING_NAMES[rank]}"


def _format_reg_date(timestamp: int) -> str:
    if timestamp == 0:
        return "未知"
    dt = datetime.fromtimestamp(timestamp, tz=timezone(timedelta(hours=8)))
    return f"{dt.year}年{dt.month}月{dt.day}日 {dt.hour}:{dt.minute}:{dt.second}"


def _format_peak_section(title: str, data: PeakData) -> str:
    return (
        f"{title}：当前段位 {_format_peak_rating(data.current_score)}"
        f" / 历史最高 {_format_peak_rating(data.history_highest_score)}"
    )


def _format_player_info(
    user_info: UserInfo,
    more_info: MoreInfo,
    *,
    team_name: str,
    peak_data: PeakData,
    peak_data_wild: PeakData,
    peak_data_expert: PeakData,
    is_online: bool,
) -> str:
    team_text = (
        f"{team_name}（战队号：{user_info.team_id}）"
        if user_info.team_id > 0
        else "未加入"
    )
    expert_text = f"专家：当前 {peak_data_expert.current_score}分 / 历史最高 {peak_data_expert.history_highest_score}分"
    return (
        f"🤖【玩家信息】\n"
        f"米米号：{user_info.user_id}\n"
        f"昵称：{user_info.nick}\n"
        f"注册时间：{_format_reg_date(more_info.reg_time)}\n"
        f"战队：{team_text}\n"
        f"VIP等级：{user_info.vip_level}\n"
        f"成就点数：{more_info.total_achieve}\n"
        f"在线状态：{'在线' if is_online else '离线'}\n"
        f"上次登录时间：{_format_reg_date(user_info.login_time)}\n"
        "\n"
        "【巅峰数据】\n"
        f"{_format_peak_section('竞技', peak_data)}\n"
        f"{_format_peak_section('狂野', peak_data_wild)}\n"
        f"{expert_text}"
    )


PLAYER_ID_KEY = "player_id"


@player_matcher.handle()
async def validate_player_id(
    state: T_State,
    player_id: int = PlayerIdArg,
) -> None:
    state[PLAYER_ID_KEY] = player_id


@player_matcher.handle()
async def handle_player(
    matcher: Matcher,
    state: T_State,
    game: SeerGame = GameClient,
) -> NoReturn:
    player_id: int = state[PLAYER_ID_KEY]

    user_info, more_info = await asyncio.gather(
        game.get_user_info(player_id),
        game.get_more_user_info(player_id),
    )

    team_name = "无"
    if user_info.team_id > 0:
        try:
            team_info = await game.get_team_info(user_info.team_id)
            team_name = team_info.name
        except SocketRecvError:
            team_name = str(user_info.team_id)

    peak_data, peak_data_wild, peak_data_expert = await asyncio.gather(
        game.get_user_peak_data(player_id),
        game.get_user_peak_wild_data(player_id),
        game.get_user_peak_expert_data(player_id),
    )

    is_online = (await game.get_user_online_info(player_id)) is not None
    await matcher.finish(
        _format_player_info(
            user_info,
            more_info,
            team_name=team_name,
            peak_data=peak_data,
            peak_data_wild=peak_data_wild,
            peak_data_expert=peak_data_expert,
            is_online=is_online,
        )
    )
