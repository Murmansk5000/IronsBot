# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any

from ironsbot.services.seer.formatting import format_possible_datetime


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
