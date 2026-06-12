# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass

PLAYER_QUERY_PREFIXES = ("查询玩家信息", "米米号")


@dataclass(slots=True)
class PlayerDetailMessages:
    collection_message: str = ""
    peak_message: str = ""


def extract_player_query_arg(text_value: str) -> str | None:
    stripped = text_value.strip()
    folded = stripped.casefold()
    for prefix in PLAYER_QUERY_PREFIXES:
        if folded.startswith(prefix.casefold()):
            return stripped[len(prefix) :].strip()
    return None


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
