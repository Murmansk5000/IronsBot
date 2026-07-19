# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ironsbot.core.commands import normalize_command_text

from .countermark_stat_rank_models import (
    CountermarkStatRankCommand,
    StatSpec,
)

MIN_COMBINATION_PARTS = 2
ANGLE_MARKERS = {
    "一角": 1,
    "1角": 1,
    "１角": 1,
    "二角": 2,
    "两角": 2,
    "2角": 2,
    "２角": 2,
    "三角": 3,
    "3角": 3,
    "３角": 3,
    "四角": 4,
    "4角": 4,
    "４角": 4,
    "五角": 5,
    "5角": 5,
    "５角": 5,
    "六角": 6,
    "6角": 6,
    "６角": 6,
}

BASE_STAT_ALIASES: dict[str, StatSpec] = {
    "攻击": StatSpec("atk", "物攻", ("atk",)),
    "物攻": StatSpec("atk", "物攻", ("atk",)),
    "防御": StatSpec("def_", "防御", ("def_",)),
    "物防": StatSpec("def_", "防御", ("def_",)),
    "特攻": StatSpec("sp_atk", "特攻", ("sp_atk",)),
    "特防": StatSpec("sp_def", "特防", ("sp_def",)),
    "速度": StatSpec("spd", "速度", ("spd",)),
    "速": StatSpec("spd", "速度", ("spd",)),
    "体力": StatSpec("hp", "体力", ("hp",)),
    "体": StatSpec("hp", "体力", ("hp",)),
    "血量": StatSpec("hp", "体力", ("hp",)),
    "生命": StatSpec("hp", "体力", ("hp",)),
}

COMPOSITE_STAT_ALIASES: dict[str, StatSpec] = {
    "双防": StatSpec("shield", "双防", ("def_", "sp_def")),
    "盾": StatSpec("shield", "双防", ("def_", "sp_def")),
    "双防和": StatSpec("shield", "双防", ("def_", "sp_def")),
    "盾和": StatSpec("shield", "双防", ("def_", "sp_def")),
    "防御特防": StatSpec("shield", "双防", ("def_", "sp_def")),
    "防御加特防": StatSpec("shield", "双防", ("def_", "sp_def")),
    "双攻": StatSpec("dual_atk", "双攻", ("atk", "sp_atk")),
    "双刀": StatSpec("dual_atk", "双攻", ("atk", "sp_atk")),
    "双攻和": StatSpec("dual_atk", "双攻", ("atk", "sp_atk")),
    "双刀和": StatSpec("dual_atk", "双攻", ("atk", "sp_atk")),
    "攻击特攻": StatSpec("dual_atk", "双攻", ("atk", "sp_atk")),
    "攻击加特攻": StatSpec("dual_atk", "双攻", ("atk", "sp_atk")),
    "总和": StatSpec("total", "总和", ("total",)),
    "总值": StatSpec("total", "总和", ("total",)),
    "总数值": StatSpec("total", "总和", ("total",)),
    "综合": StatSpec("total", "总和", ("total",)),
}

STAT_ALIASES: dict[str, StatSpec] = {
    **BASE_STAT_ALIASES,
    **COMPOSITE_STAT_ALIASES,
}

COMBINABLE_STAT_ALIASES: tuple[tuple[str, StatSpec], ...] = tuple(
    sorted(
        {
            **BASE_STAT_ALIASES,
            "双防": COMPOSITE_STAT_ALIASES["双防"],
            "盾": COMPOSITE_STAT_ALIASES["盾"],
            "双攻": COMPOSITE_STAT_ALIASES["双攻"],
            "双刀": COMPOSITE_STAT_ALIASES["双刀"],
        }.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


_NON_STAT_COUNTERMARK_RANK_COMMANDS = {
    normalize_command_text(command)
    for command in (
        "刻印榜",
        "刻印图鉴榜",
        "样本刻印榜",
        "样本刻印图鉴榜",
        "机器人刻印榜",
        "机器人刻印图鉴榜",
    )
}

def parse_countermark_stat_rank_command(
    text: str,
) -> CountermarkStatRankCommand | None:
    normalized = normalize_command_text(text)
    has_angle_marker = any(marker in normalized for marker in ANGLE_MARKERS)
    has_countermark_marker = "刻印" in normalized
    if not normalized.endswith("榜") or (
        not has_countermark_marker and not has_angle_marker
    ):
        return None
    if normalized in _NON_STAT_COUNTERMARK_RANK_COMMANDS:
        return None

    scope = "all"
    stat_text = normalized
    for marker in ("所有", "全部", "全体"):
        if marker in stat_text:
            scope = "all"
            stat_text = stat_text.replace(marker, "")

    stat_text, has_all_marker = _strip_single_all_marker(stat_text)
    if has_all_marker:
        scope = "all"

    angle_count = None
    for marker, marker_angle_count in ANGLE_MARKERS.items():
        if marker in stat_text:
            scope = "angle"
            angle_count = marker_angle_count
            stat_text = stat_text.replace(marker, "")

    for marker in ("排行榜", "排行", "数值", "属性", "刻印", "榜"):
        stat_text = stat_text.replace(marker, "")

    stat = parse_stat_spec(stat_text)
    return CountermarkStatRankCommand(
        stat=stat,
        scope=scope,
        angle_count=angle_count,
    )


def parse_stat_spec(text: str) -> StatSpec | None:
    if stat := STAT_ALIASES.get(text):
        return stat

    remaining = text
    parts: list[StatSpec] = []
    while remaining:
        for alias, stat in COMBINABLE_STAT_ALIASES:
            if remaining.startswith(alias):
                parts.append(stat)
                remaining = remaining.removeprefix(alias)
                break
        else:
            return None

    if len(parts) < MIN_COMBINATION_PARTS:
        return None

    components: list[str] = []
    titles: list[str] = []
    for part in parts:
        components.extend(part.components or (part.key,))
        titles.append(part.title)

    return StatSpec(
        key="combo:" + "+".join(components),
        title="".join(titles),
        components=tuple(components),
    )

def _strip_single_all_marker(text: str) -> tuple[str, bool]:
    all_scope = False
    if text.startswith("全刻印"):
        text = text.removeprefix("全")
        all_scope = True
    if text.startswith("刻印全"):
        text = "刻印" + text.removeprefix("刻印全")
        all_scope = True
    return text, all_scope
