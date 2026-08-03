# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.local_rank_formatting import format_peak_rating_score
from ironsbot.services.seer.rank_list_formatting import now_text
from ironsbot.services.seer.rank_list_models import RANK_LIST_SIZE, GlobalRankSpec

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any


def format_global_rank_line(
    item: Any,
    *,
    index: int,
    spec: GlobalRankSpec,
) -> str:
    rank = index + 1
    return f"{rank}. {item.nick}（{item.id}） {_format_score(item.score, spec)}"


def format_global_rank_score(score: int, spec: GlobalRankSpec) -> str:
    return _format_score(score, spec)


def _format_score(score: int, spec: GlobalRankSpec) -> str:
    if spec.score_format == "peak_rating":
        return f"{format_peak_rating_score(score)}（{score}）"
    return f"{score}{spec.unit}"


def format_global_rank_message(
    spec: GlobalRankSpec,
    items: Sequence[Any],
    *,
    timestamp: str | None = None,
    start_rank: int = 1,
    requested_count: int = RANK_LIST_SIZE,
) -> str:
    if not items:
        return f"❌找不到{spec.title}数据。"

    from ironsbot.services.seer.rank_list_formatting import format_rank_window

    range_text = format_rank_window(start_rank, len(items), requested_count)
    if range_text:
        lines = [f"{spec.title}（{range_text}，截至{timestamp or now_text()}）"]
    else:
        lines = [f"{spec.title}（截至{timestamp or now_text()}）"]
    lines.extend(
        format_global_rank_line(
            item,
            index=start_rank - 1 + index,
            spec=spec,
        )
        for index, item in enumerate(items)
    )
    return "\n".join(lines)
