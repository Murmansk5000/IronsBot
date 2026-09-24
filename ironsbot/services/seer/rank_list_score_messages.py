# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.rank_list_models import RANK_LIST_MAX_SIZE, GlobalRankSpec

if TYPE_CHECKING:
    from typing import Any

from ironsbot.services.seer.rank_list_global_messages import (
    format_global_rank_line,
    format_global_rank_score,
)

_PROBE_LIMIT_MESSAGE = "已达到分数查找探针上限，完整同分范围尚未确认。"


def format_global_rank_score_message(
    spec: GlobalRankSpec,
    result: Any,
    *,
    display_limit: int = RANK_LIST_MAX_SIZE,
    timestamp: str,
) -> str:
    score_text = format_global_rank_score(result.target_score, spec)
    if not result.queried:
        return f"❌{spec.title}分数查询未启用。"
    if not result.items:
        if result.budget_exhausted:
            return f"❌{spec.title}分数查询未完成。\n{_PROBE_LIMIT_MESSAGE}"
        if result.boundary_score is None:
            return f"❌找不到{spec.title}数据。"
        if result.target_score < result.boundary_score:
            boundary_score = format_global_rank_score(result.boundary_score, spec)
            return (
                f"❌{score_text}不在{spec.title}前 {result.searched_limit} 名范围内。\n"
                f"当前范围末位约为 {boundary_score}。"
            )
        proof_lines = _format_score_gap_proof(spec, result)
        if proof_lines:
            lines = [f"❌{spec.title}没有{score_text}的用户。"]
            lines.append("相邻分数段：")
            lines.extend(proof_lines)
        else:
            lines = [
                f"❌{spec.title}前 {result.searched_limit} 名没有{score_text}的用户。"
            ]
        return "\n".join(lines)

    shown = score_player_items_for_display(result, display_limit)
    start_rank = result.start_rank or shown[0].rank_index + 1
    end_rank = result.end_rank or shown[-1].rank_index + 1
    population = (
        f"已确认 {len(result.items)} 人"
        if result.budget_exhausted
        else f"第 {start_rank}-{end_rank} 名，共 {result.total_count} 人"
    )
    lines = [f"{spec.title}（{score_text}，{population}，截至{timestamp}）"]
    lines.extend(
        format_global_rank_line(item, index=item.rank_index, spec=spec)
        for item in shown
    )
    population_count = (
        len(result.items) if result.budget_exhausted else result.total_count
    )
    hidden_count = max(population_count - len(shown), len(result.items) - len(shown))
    if hidden_count > 0:
        lines.append(f"...另 {hidden_count} 人未展示")
    if result.budget_exhausted:
        lines.append(_PROBE_LIMIT_MESSAGE)
    elif result.truncated:
        lines.append("同分段过长，已按安全上限停止继续翻页。")
    return "\n".join(lines)


def score_items_for_display(items: list[Any], display_limit: int) -> list[Any]:
    """Show both edges of a large same-score segment instead of only its head."""

    limit = max(1, display_limit)
    if len(items) <= limit:
        return items
    head_count = (limit + 1) // 2
    tail_count = limit - head_count
    if tail_count == 0:
        return items[:head_count]
    return [*items[:head_count], *items[-tail_count:]]


def score_gap_items_for_display(result: Any) -> list[Any]:
    """Return the player rows rendered as proof for a missing exact score."""

    items: list[Any] = []
    for gap in (
        getattr(result, "higher_gap", None),
        getattr(result, "lower_gap", None),
    ):
        if gap is not None:
            items.extend(getattr(gap, "items", []))
    return items


def score_player_items_for_display(result: Any, display_limit: int) -> list[Any]:
    """Return exactly the numbered player rows rendered by the formatter."""

    if not result.queried:
        return []
    if result.items:
        return score_items_for_display(result.items, display_limit)
    if (
        result.budget_exhausted
        or result.boundary_score is None
        or result.target_score < result.boundary_score
    ):
        return []
    return score_gap_items_for_display(result)


def _format_score_gap_proof(spec: GlobalRankSpec, result: Any) -> list[str]:
    lines: list[str] = []
    for gap in (
        getattr(result, "higher_gap", None),
        getattr(result, "lower_gap", None),
    ):
        if gap is None:
            continue
        rank_text = (
            f"第 {gap.start_rank} 名"
            if gap.start_rank == gap.end_rank
            else f"第 {gap.start_rank}-{gap.end_rank} 名"
        )
        lines.append(
            f"{format_global_rank_score(gap.score, spec)}：{rank_text}，"
            f"共 {gap.total_count} 人"
        )
        lines.extend(
            format_global_rank_line(item, index=item.rank_index, spec=spec)
            for item in getattr(gap, "items", [])
        )
        if getattr(gap, "truncated", False):
            lines.append("该分数段可能跨页，已显示当前页内可确认部分。")
    return lines
