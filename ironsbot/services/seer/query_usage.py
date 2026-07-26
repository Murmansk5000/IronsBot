# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class SeerQueryUsageSection:
    feature: str
    lines: tuple[str, ...]


SEER_QUERY_USAGE_SECTIONS = (
    SeerQueryUsageSection(
        feature="seer_player",
        lines=(
            "【玩家】",
            "米米号123456 / 查询玩家信息123456",
            "查询指定米米号后，回复数字查看收集、巅峰、群星牌或阵容。",
            "已绑定用户可直接发送：米米号 / 收集 / 巅峰 / 群星牌 / 阵容。",
            "首次成功查询后可按提示设为默认米米号；可发送“解绑米米号”。",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_team",
        lines=(
            "【战队】",
            "战队123456 / 查询战队信息123456",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_pet",
        lines=(
            "【精灵、技能、魂印、立绘、皮肤】",
            "精灵雷伊 / 雷伊魂印 / 圣武技能",
            "雷伊立绘 / 雷伊皮肤 / 皮肤雷伊",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_mintmark",
        lines=(
            "【刻印、宝石、刻印榜】",
            "刻印V8 / 精灵王刻印 / 宝石绝命",
            "刻印攻击榜 / 六角双攻榜 / 特攻双防刻印榜",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_equipment",
        lines=(
            "【套装、部件、称号】",
            "典狱套装 / 部件漫游者 / 称号神话",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_type",
        lines=(
            "【属性与异常】",
            "属性圣灵 / 火战斗属性 / 属性火+战斗",
            "异常中毒 / 冻伤异常",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_peak",
        lines=(
            "【巅峰相关】",
            "竞技池 / 专家池 / 巅峰投票",
            "竞技套装榜 / 狂野称号榜",
            "竞技精灵月榜 / 竞技精灵总榜",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_autocard",
        lines=(
            "【群星牌】",
            "群星牌布布种子 / 布布种子群星牌",
            "群星牌卡98（按卡牌 ID） / 群星牌榜",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_rank",
        lines=(
            "【榜单入口】",
            "榜单 / 榜单帮助 / 榜单情况 / 样本情况",
            "图鉴榜 / 群星牌榜 / 竞技段位榜 / 专家段位榜",
            "纯数字查米米号；名次带“名”，分数带“分/点”。",
            "示例：成就榜123456 / 成就榜200名 / 成就榜5000点",
        ),
    ),
    SeerQueryUsageSection(
        feature="seer_data",
        lines=(
            "【数据工具】",
            "下周预告 / 新增成就（新成就） / 数据版本 / 赛季倒计时",
        ),
    ),
)


def build_seer_query_usage_message(
    feature_is_visible: Callable[[str], bool],
) -> str:
    sections = [
        section
        for section in SEER_QUERY_USAGE_SECTIONS
        if feature_is_visible(section.feature)
    ]
    if not sections:
        return "当前会话没有可用的赛尔号查询子功能。"

    lines: list[str] = []
    for section in sections:
        if lines:
            lines.append("")
        lines.extend(section.lines)
    return "\n".join(lines)
