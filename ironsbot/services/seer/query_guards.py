# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.services.seer.countermark_stat_rank import (
    parse_countermark_stat_rank_command,
)
from ironsbot.services.seer.rank_list import parse_rank_list_command

_RANK_SUFFIXES = ("榜", "排行", "排行榜")
_RANK_HINTS = (
    "图鉴",
    "成就",
    "精灵",
    "皮肤",
    "套装",
    "部件",
    "座驾",
    "刻印",
    "宝石",
    "属性",
    "异常",
    "称号",
    "竞技",
    "狂野",
    "专家",
    "巅峰",
    "胜率",
    "场次",
    "段位",
)


def normalize_query_text(text: str) -> str:
    return "".join(text.split()).lower()


def is_rank_query_text(text: str) -> bool:
    """Return whether text should be handled by rank commands, not fuzzy lookup."""
    if parse_rank_list_command(text) is not None:
        return True

    if parse_countermark_stat_rank_command(text) is not None:
        return True

    normalized = normalize_query_text(text)
    return normalized.endswith(_RANK_SUFFIXES) and any(
        hint in normalized for hint in _RANK_HINTS
    )


__all__ = ["is_rank_query_text", "normalize_query_text"]
