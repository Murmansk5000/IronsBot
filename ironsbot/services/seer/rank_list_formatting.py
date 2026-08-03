# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ironsbot.services.seer.rank_list_models import (
    MAX_CACHE_INTERVALS_SHOWN,
    RANK_LIST_SIZE,
    GlobalRankSpec,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any


def now_text() -> str:
    now = datetime.now(timezone(timedelta(hours=8)))
    return now.strftime("%Y-%m-%d %H:%M:%S")


def timestamp_text(timestamp: float) -> str:
    value = datetime.fromtimestamp(timestamp, timezone(timedelta(hours=8)))
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_rank_window(
    start_rank: int,
    actual_count: int,
    requested_count: int,
) -> str:
    if start_rank == 1 and requested_count == RANK_LIST_SIZE:
        return ""
    if actual_count <= 1 or requested_count <= 1:
        return f"第 {start_rank} 名"
    return f"第 {start_rank}-{start_rank + actual_count - 1} 名"


def page_cache_rank_interval(
    page: Any,
    _spec: GlobalRankSpec,
) -> tuple[int, int] | None:
    expected_count = int(getattr(page, "expected_count", page.item_count))
    if expected_count <= 0:
        return None

    start_rank = page.start_index + 1
    end_rank = page.start_index + expected_count
    return max(1, start_rank), max(1, end_rank)


def merge_rank_intervals(
    intervals: Sequence[tuple[int, int]],
) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
            continue

        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged


def format_rank_intervals(intervals: Sequence[tuple[int, int]]) -> str:
    if not intervals:
        return "无"

    shown = intervals[:MAX_CACHE_INTERVALS_SHOWN]
    text = "、".join(
        str(start) if start == end else f"{start}-{end}"
        for start, end in shown
    )
    if len(intervals) > len(shown):
        text += f"、...另 {len(intervals) - len(shown)} 段"
    return text
