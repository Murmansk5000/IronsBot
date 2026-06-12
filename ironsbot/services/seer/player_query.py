# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

PLAYER_QUERY_PREFIXES = ("查询玩家信息", "米米号")


@dataclass(slots=True)
class PlayerDetailMessages:
    collection_message: str = ""
    peak_message: str = ""


@dataclass(frozen=True, slots=True)
class PlayerQuerySectionPlan:
    show_local_rank: bool
    has_collection: bool
    needs_peak_section: bool
    needs_online_info: bool
    local_rank_enabled: bool

    @property
    def needs_detail_task(self) -> bool:
        return (
            self.has_collection
            or self.needs_peak_section
            or self.local_rank_enabled
        )


def extract_player_query_arg(text_value: str) -> str | None:
    stripped = text_value.strip()
    folded = stripped.casefold()
    for prefix in PLAYER_QUERY_PREFIXES:
        if folded.startswith(prefix.casefold()):
            return stripped[len(prefix) :].strip()
    return None


def plan_player_query_sections(
    sections: Iterable[str],
    *,
    local_rank_enabled: bool,
) -> PlayerQuerySectionPlan:
    enabled_sections = set(sections)
    has_collection = bool(
        {"collection", "rank", "local_rank", "achievement"} & enabled_sections
    )
    return PlayerQuerySectionPlan(
        show_local_rank="local_rank" in enabled_sections,
        has_collection=has_collection,
        needs_peak_section="peak" in enabled_sections,
        needs_online_info="basic" in enabled_sections,
        local_rank_enabled=local_rank_enabled,
    )


def player_detail_commands(
    *,
    has_collection: bool,
    has_peak: bool,
) -> tuple[str, ...]:
    commands: list[str] = []
    if has_collection:
        commands.append("收集")
    if has_peak:
        commands.append("巅峰")
    return tuple(commands)


def player_query_in_progress_message(player_id: int) -> str:
    return (
        f"⏳ 正在查询米米号 {player_id}，请等当前查询完成。\n"
        "米米号查询需要连接游戏服务器；收集、巅峰和全服排行数据会更慢，"
        "排名越靠后可能查得越久，多人同时查询时也可能需要排队。"
    )


def player_query_wait_message(remaining: int) -> str:
    return (
        f"⏳ 刚刚已经发起过米米号查询，请 {remaining} 秒后再试。\n"
        "收集、巅峰和全服排行数据会更慢，排名越靠后可能查得越久，"
        "多人同时查询时也可能需要排队。"
    )


def player_detail_pending_message(label: str) -> str:
    return (
        f"⏳ {label}还在查询中，请稍等后再试。\n"
        "这部分需要拉取收集、全服榜或赛季榜数据，排名越靠后可能越慢，"
        "多人同时查询时也可能需要排队。"
    )
