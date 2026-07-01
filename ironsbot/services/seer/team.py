# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any


def team_query_in_progress_message(team_id: int) -> str:
    return (
        f"⏳ 正在查询战队 {team_id}，请等当前查询完成。\n"
        "战队查询需要连接赛尔号游戏服务器；服务器维护、开服波动或多人同时查询时会比较慢。"
    )


def team_query_wait_message(remaining: int) -> str:
    return (
        f"⏳ 刚刚已经发起过战队查询，请 {remaining} 秒后再试。\n"
        "战队查询需要连接游戏服务器，短时间连续查询容易排队或超时。"
    )


def format_team_unavailable_message(team_id: int) -> str:
    return (
        f"❌ 战队 {team_id} 暂时查不了："
        "查询需要连接赛尔号游戏服务器；当前服务器维护、未开放或无头客户端未登录。"
    )


def format_team_timeout_message(team_id: int) -> str:
    return f"❌ 战队 {team_id} 查询超时，请稍后再试。"


def format_team_socket_error_message(team_id: int, socket_error_text: str) -> str:
    return f"❌ 战队 {team_id} {socket_error_text}"


def format_team_generic_error_message(team_id: int, error: object) -> str:
    return f"❌ 战队 {team_id} 查询失败：{error}"


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


def format_team_info(info: Any, enabled_sections: set[str]) -> str:
    slogan = info.slogan or "（无）"
    notice = info.notice or "（无）"

    lines = [f"🏰【战队信息：{info.name}】"]
    _append_section(
        lines,
        enabled_sections,
        "basic",
        [
            f"战队ID：{info.team_id}",
            f"队长：{info.leader}（米米号）",
            f"战队等级：{info.new_team_level}",
        ],
    )
    _append_section(
        lines,
        enabled_sections,
        "resource",
        [
            f"成员数：{info.member_count}",
            f"战队资源：{info.score}",
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
