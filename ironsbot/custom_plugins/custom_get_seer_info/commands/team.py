# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from typing import Any

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.typing import T_State

from ironsbot.custom_plugins.common.query_guard import QueryGuard
from ironsbot.custom_plugins.headless_seer_notice.state import (
    mark_headless_available,
    mark_headless_unavailable,
)
from ironsbot.custom_plugins.message_actions import finish_event_reply
from ironsbot.plugins.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..config import plugin_config
from ..group import matcher_group
from ._args import has_numeric_arg, parse_numeric_id
from ._client import get_game_client
from ._errors import format_socket_recv_error
from ._format import format_possible_datetime

TEAM_ID_KEY = "team_id"
QUERY_CONFIG = plugin_config.seer_query_config
TEAM_QUERY_GUARD = QueryGuard(
    success_namespace="custom_get_seer_info.team_query.success",
    failure_namespace="custom_get_seer_info.team_query.failure",
    success_cooldown=lambda: QUERY_CONFIG.team.rate_limit_seconds,
    failure_cooldown=lambda: QUERY_CONFIG.team.failure_rate_limit_seconds,
)

team_matcher = matcher_group.on_message(
    rule=(
        startswith_or_endswith(prefixes=("战队", "查询战队信息"), suffixes=())
        & has_numeric_arg
        & no_reply()
    ),
)


def _append_section(
    lines: list[str],
    enabled_sections: set[str],
    section: str,
    section_lines: list[str],
) -> None:
    if section not in enabled_sections:
        return

    if lines and lines[-1] != "":
        lines.append("")
    lines.extend(section_lines)


def _format_team_info(info: Any, enabled_sections: set[str]) -> str:
    slogan = info.slogan or "（无）"
    notice = info.notice or "（无）"

    lines = [f"🏰【战队扩展信息：{info.name}】"]
    _append_section(
        lines,
        enabled_sections,
        "basic",
        [
            f"战队ID：{info.team_id}",
            f"队长：{info.leader}（米米号）",
            f"成员数：{info.member_count}",
        ],
    )
    _append_section(
        lines,
        enabled_sections,
        "resource",
        [
            "【等级与资源】",
            f"战队等级：{info.new_team_level}",
            f"战队经验：{info.exp}",
            f"战队资源：{info.score}",
            f"超级核心数量：{info.super_core_num}",
            f"最近缴纳时间：{format_possible_datetime(info.last_pay_time)}",
        ],
    )
    _append_section(
        lines,
        enabled_sections,
        "facilities",
        [
            "【设施等级】",
            f"科技中心：{info.tech_center_level}",
            f"奖励中心：{info.bonus_center_level}",
            f"资源中心：{info.res_center_level}",
            f"战队Boss总伤害：{info.total_boss_dmg}",
        ],
    )
    _append_section(
        lines,
        enabled_sections,
        "status",
        [
            "【权限与状态】",
            f"兴趣/分类值：{info.interest}",
            f"加入标记：{info.join_flag}",
            f"访问标记：{info.visit_flag}",
            f"功能禁用标记：{info.team_func_disalbed}",
            f"绘图数据：{info.drawing_uint}",
        ],
    )
    _append_section(
        lines,
        enabled_sections,
        "logo",
        [
            "【Logo参数】",
            f"背景：{info.logo_bg}",
            f"图标：{info.logo_icon}",
            f"颜色：{info.logo_color}",
            f"文字颜色：{info.txt_color}",
            f"Logo文字：{info.logo_word or '（无）'}",
        ],
    )
    _append_section(
        lines,
        enabled_sections,
        "text",
        [
            "【文本】",
            f"标语：{slogan}",
            f"公告：{notice}",
        ],
    )
    return "\n".join(lines)


def _team_query_in_progress_message(team_id: int) -> str:
    return (
        f"⏳ 正在查询战队 {team_id}，请等当前查询完成。\n"
        "战队查询需要连接赛尔号游戏服务器；服务器维护、开服波动或多人同时查询时会比较慢。"
    )


def _team_query_wait_message(remaining: int) -> str:
    return (
        f"⏳ 刚刚已经发起过战队查询，请 {remaining} 秒后再试。\n"
        "战队查询需要连接游戏服务器，短时间连续查询容易排队或超时。"
    )


async def _finish_team_query_failure(
    matcher: Matcher,
    event: MessageEvent,
    message: str,
) -> None:
    TEAM_QUERY_GUARD.clear_in_progress(event.user_id)
    TEAM_QUERY_GUARD.penalize_failure(event.user_id)
    await finish_event_reply(
        matcher,
        event,
        message,
        mention_sender=True,
    )


@team_matcher.handle()
async def validate_team_id(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    state[TEAM_ID_KEY] = await parse_numeric_id(
        matcher,
        state,
        min_value=100000,
        max_value=2_000_000_000,
        error_message="❌ 战队ID范围必须在 100000~2000000000 之间！",
    )
    team_id: int = state[TEAM_ID_KEY]

    in_progress_team_id = TEAM_QUERY_GUARD.in_progress_subject(event.user_id)
    if in_progress_team_id is not None:
        await finish_event_reply(
            matcher,
            event,
            _team_query_in_progress_message(in_progress_team_id),
            mention_sender=True,
        )

    remaining = TEAM_QUERY_GUARD.remaining_seconds(event.user_id)
    if remaining > 0:
        await finish_event_reply(
            matcher,
            event,
            _team_query_wait_message(remaining),
            mention_sender=True,
        )

    TEAM_QUERY_GUARD.set_in_progress(event.user_id, team_id)


@team_matcher.handle()
async def handle_team(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    team_id: int = state[TEAM_ID_KEY]

    try:
        game = get_game_client()
        team_info = await asyncio.wait_for(
            game.get_team_info(team_id),
            timeout=plugin_config.seer_query_config.team.timeout_seconds,
        )
        await mark_headless_available(source="战队查询", user_id=int(game.user_id))
        team_message = _format_team_info(
            team_info,
            set(plugin_config.seer_query_config.team.sections),
        )
    except FinishedException:
        raise
    except (NotLoggedInError, DisconnectedError) as e:
        await mark_headless_unavailable(str(e), source="战队查询")
        await _finish_team_query_failure(
            matcher,
            event,
            (
                f"❌ 战队 {team_id} 暂时查不了："
                "查询需要连接赛尔号游戏服务器；当前服务器维护、未开放或无头客户端未登录。"
            ),
        )
        return
    except TimeoutError:
        await _finish_team_query_failure(
            matcher,
            event,
            f"❌ 战队 {team_id} 查询超时，请稍后再试。",
        )
        return
    except SocketRecvError as e:
        await _finish_team_query_failure(
            matcher,
            event,
            f"❌ 战队 {team_id} {format_socket_recv_error(e)}",
        )
        return
    except Exception as e:  # noqa: BLE001
        await _finish_team_query_failure(
            matcher,
            event,
            f"❌ 战队 {team_id} 查询失败：{e}",
        )
        return

    TEAM_QUERY_GUARD.clear_in_progress(event.user_id)
    TEAM_QUERY_GUARD.penalize_success(event.user_id)
    await finish_event_reply(
        matcher,
        event,
        team_message,
        mention_sender=True,
    )
