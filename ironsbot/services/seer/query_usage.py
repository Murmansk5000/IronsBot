# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.shared.features.visibility import feature_visible_for_help

if TYPE_CHECKING:
    from nonebot.adapters import Event


@dataclass(frozen=True, slots=True)
class SeerQueryUsageSection:
    feature: str
    lines: tuple[str, ...]


SEER_QUERY_USAGE_SECTIONS = (
    SeerQueryUsageSection(
        feature="seer_player",
        lines=(
            "【玩家】feature: seer_player",
            "米米号123456 / 查询玩家信息123456",
            "首次成功查询可设置默认米米号；之后直接发送米米号 / 收集 / 巅峰 / 群星牌。",
            "也可直接发送：收集123456 / 巅峰123456 / 群星牌123456。",
            "绑定米米号123456 / 更改米米号123456 / 解绑米米号",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_team",
        lines=(
            "【战队】feature: seer_team",
            "战队123456 / 查询战队信息123456",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_pet",
        lines=(
            "【精灵、技能、魂印、立绘、皮肤】feature: seer_pet",
            "精灵雷伊 / 雷伊魂印 / 圣武技能",
            "雷伊立绘 / 雷伊皮肤 / 皮肤雷伊",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_mintmark",
        lines=(
            "【刻印、宝石、刻印榜】feature: seer_mintmark",
            "刻印V8 / 精灵王刻印 / 宝石绝命",
            "刻印攻击榜 / 六角双攻榜 / 特攻双防刻印榜",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_equipment",
        lines=(
            "【套装、部件、称号】feature: seer_equipment",
            "典狱套装 / 部件漫游者 / 称号神话",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_type",
        lines=(
            "【属性与异常】feature: seer_type",
            "属性圣灵 / 火战斗属性 / 属性火+战斗",
            "异常中毒 / 冻伤异常",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_peak",
        lines=(
            "【巅峰相关】feature: seer_peak",
            "竞技池 / 专家池 / 巅峰投票",
            "竞技套装榜 / 狂野称号榜",
            "竞技精灵月榜 / 竞技精灵总榜",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_autocard",
        lines=(
            "【群星牌】feature: seer_autocard",
            "群星牌布布种子 / 布布种子群星牌",
            "群星牌卡98（按卡牌 ID） / 群星牌榜",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_rank",
        lines=(
            "【榜单入口】feature: seer_rank",
            "榜单 / 榜单帮助 / 榜单情况 / 样本情况",
            "图鉴榜 / 群星牌榜 / 竞技段位榜 / 专家段位榜",
            "纯数字查米米号；名次带“名”，分数带“分/点”。",
            "示例：成就榜123456 / 成就榜200名 / 成就榜5000点",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_data",
        lines=(
            "【数据工具】feature: seer_data",
            "下周预告 / 数据版本 / 赛季倒计时",
        ),
    ),
)


def build_seer_query_usage_message(event: Event) -> str:
    sections = [
        section
        for section in SEER_QUERY_USAGE_SECTIONS
        if feature_visible_for_help(event, section.feature)
    ]
    if not sections:
        return "当前会话没有可用的赛尔号查询子功能。"

    lines: list[str] = []
    for section in sections:
        if lines:
            lines.append("")
        lines.extend(section.lines)
    return "\n".join(lines)


__all__ = [
    "SEER_QUERY_USAGE_SECTIONS",
    "SeerQueryUsageSection",
    "build_seer_query_usage_message",
]
