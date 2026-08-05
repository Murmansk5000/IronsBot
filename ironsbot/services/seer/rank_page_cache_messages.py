# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.seer.rank_list_formatting import (
    format_rank_intervals,
    merge_rank_intervals,
    page_cache_rank_interval,
)
from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS, GlobalRankSpec

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

    from ironsbot.services.seer.rank_list_models import RankPageCacheRefreshCommand


_FRESH = "fresh"
_PARTIAL = "partial"
_STALE = "stale"
_MISSING = "missing"
_STATUS_SYMBOLS = {
    _FRESH: "█",
    _PARTIAL: "▒",
    _STALE: "▓",
    _MISSING: "░",
}
_STATUS_TIEBREAK = {
    _FRESH: 0,
    _STALE: 1,
    _PARTIAL: 2,
    _MISSING: 3,
}
_PROGRESS_WIDTH = 100


@dataclass(frozen=True, slots=True)
class _CoverageSegment:
    start_index: int
    end_index: int
    status: str


@dataclass(frozen=True, slots=True)
class _RankPageCoverage:
    target_count: int
    fresh_count: int
    partial_count: int
    stale_count: int
    missing_count: int
    segments: tuple[_CoverageSegment, ...]

    @property
    def stored_count(self) -> int:
        return self.fresh_count + self.partial_count + self.stale_count


def _page_status(page: Any) -> str:
    if getattr(page, "is_partial", False):
        return _PARTIAL
    if getattr(page, "is_stale", False):
        return _STALE
    return _FRESH


def _page_interval(page: Any, *, target_count: int) -> tuple[int, int] | None:
    start_index = max(int(page.start_index), 0)
    expected_count = max(int(getattr(page, "expected_count", page.item_count)), 0)
    end_index = min(start_index + expected_count, target_count)
    if end_index <= start_index:
        return None
    return start_index, end_index


def _rank_page_coverage(
    pages: Sequence[Any],
    *,
    target_count: int,
) -> _RankPageCoverage:
    fresh_count = 0
    partial_count = 0
    stale_count = 0
    missing_count = 0
    segments: list[_CoverageSegment] = []
    cursor = 0
    for page in sorted(pages, key=lambda item: int(item.start_index)):
        interval = _page_interval(page, target_count=target_count)
        if interval is None:
            continue
        start_index, end_index = interval
        if start_index > cursor:
            segments.append(_CoverageSegment(cursor, start_index, _MISSING))
            missing_count += start_index - cursor
        start_index = max(start_index, cursor)
        if end_index <= start_index:
            continue
        expected_count = end_index - start_index
        actual_count = min(max(int(page.item_count), 0), expected_count)
        status = _page_status(page)
        segments.append(_CoverageSegment(start_index, end_index, status))
        if status == _FRESH:
            fresh_count += actual_count
        elif status == _PARTIAL:
            partial_count += actual_count
        else:
            stale_count += actual_count
        missing_count += expected_count - actual_count
        cursor = end_index
    if cursor < target_count:
        segments.append(_CoverageSegment(cursor, target_count, _MISSING))
        missing_count += target_count - cursor
    return _RankPageCoverage(
        target_count=target_count,
        fresh_count=fresh_count,
        partial_count=partial_count,
        stale_count=stale_count,
        missing_count=missing_count,
        segments=tuple(segments),
    )


def _progress_bar(coverage: _RankPageCoverage, *, width: int) -> str:
    if coverage.target_count <= 0:
        return ""
    symbols: list[str] = []
    for index in range(width):
        start_index = index * coverage.target_count // width
        end_index = (index + 1) * coverage.target_count // width
        if end_index <= start_index:
            end_index = start_index + 1
        candidates = [
            (
                min(end_index, segment.end_index)
                - max(start_index, segment.start_index),
                _STATUS_TIEBREAK[segment.status],
                segment.status,
            )
            for segment in coverage.segments
            if segment.start_index < end_index and segment.end_index > start_index
        ]
        _, _priority, status = max(candidates, default=(0, 0, _MISSING))
        symbols.append(_STATUS_SYMBOLS[status])
    return "".join(symbols)


def _percentage(value: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{value * 100 / total:.1f}%"


def _position_scale(*, target_count: int, width: int) -> str:
    midpoint = max((target_count + 1) // 2, 1)
    start_label = "1"
    middle_label = f"{midpoint:,}"
    end_label = f"{target_count:,}"
    middle_start = max(width // 2 - len(middle_label) // 2, len(start_label) + 1)
    end_start = max(width - len(end_label), middle_start + len(middle_label) + 1)
    return (
        start_label
        + " " * (middle_start - len(start_label))
        + middle_label
        + " " * (end_start - middle_start - len(middle_label))
        + end_label
    )


def _coverage_lines(coverage: _RankPageCoverage) -> list[str]:
    target_count = coverage.target_count
    return [
        "图例：█ 新鲜完整｜▓ 过期｜▒ 部分｜░ 缺失",
        (
            f"覆盖：{coverage.stored_count}/{target_count} 名"
            f"（{_percentage(coverage.stored_count, target_count)}）"
        ),
        (
            f"新鲜完整：{coverage.fresh_count} 名"
            f"（{_percentage(coverage.fresh_count, target_count)}）｜"
            f"部分：{coverage.partial_count} 名"
            f"（{_percentage(coverage.partial_count, target_count)}）"
        ),
        (
            f"过期：{coverage.stale_count} 名"
            f"（{_percentage(coverage.stale_count, target_count)}）｜"
            f"缺失：{coverage.missing_count} 名"
            f"（{_percentage(coverage.missing_count, target_count)}）"
        ),
    ]


def build_rank_page_cache_status_message(  # noqa: PLR0913 - message inputs are independent
    spec: GlobalRankSpec,
    pages: Sequence[Any],
    *,
    ttl_seconds: int,
    target_limit: int | str | None = None,
    target_label: str | None = None,
    next_ranges: Sequence[tuple[str, int, int]] = (),
) -> str:
    inferred_target = max(
        (
            int(page.start_index)
            + max(int(getattr(page, "expected_count", page.item_count)), 0)
            for page in pages
        ),
        default=0,
    )
    numeric_target_limit = target_limit if isinstance(target_limit, int) else None
    resolved_target = max(numeric_target_limit or inferred_target, 0)
    target_text = target_label or (
        target_limit if isinstance(target_limit, str) else None
    ) or (
        f"前 {resolved_target} 名" if resolved_target else None
    )
    coverage = _rank_page_coverage(pages, target_count=resolved_target)

    partial_pages = [page for page in pages if getattr(page, "is_partial", False)]
    valid_pages = [
        page
        for page in pages
        if not page.is_stale and not getattr(page, "is_partial", False)
    ]
    stale_pages = [
        page
        for page in pages
        if page.is_stale and not getattr(page, "is_partial", False)
    ]
    valid_intervals = merge_rank_intervals(
        [
            interval
            for page in valid_pages
            if (interval := page_cache_rank_interval(page, spec)) is not None
        ]
    )
    stale_intervals = merge_rank_intervals(
        [
            interval
            for page in stale_pages
            if (interval := page_cache_rank_interval(page, spec)) is not None
        ]
    )
    partial_intervals = merge_rank_intervals(
        [
            interval
            for page in partial_pages
            if (interval := page_cache_rank_interval(page, spec)) is not None
        ]
    )

    lines = [
        f"📦【{spec.title}缓存】",
    ]
    if target_text is not None:
        lines.insert(1, f"目标：{target_text}")
    if resolved_target:
        position_scale = _position_scale(
            target_count=resolved_target,
            width=_PROGRESS_WIDTH,
        )
        lines.extend(
            [
                f"进度：{_progress_bar(coverage, width=_PROGRESS_WIDTH)}",
                f"位置：{position_scale}",
                *_coverage_lines(coverage),
            ]
        )
    if not pages:
        lines.append("当前没有缓存区间。")
    else:
        lines.extend(
            [
                f"新鲜完整区间：{len(valid_pages)} 段，{coverage.fresh_count} 名",
                f"有效区间：{format_rank_intervals(valid_intervals)}",
            ]
        )
    if partial_pages:
        lines.extend(
            [
                f"部分缺失：{len(partial_pages)} 段，现存 {coverage.partial_count} 名",
                f"缺失区间：{format_rank_intervals(partial_intervals)}",
            ]
        )
    if stale_pages:
        lines.extend(
            [
                f"过期缓存：{len(stale_pages)} 段，{coverage.stale_count} 名",
                f"过期区间：{format_rank_intervals(stale_intervals)}",
            ]
        )
    lines.append(f"TTL：{ttl_seconds} 秒")
    if next_ranges:
        lines.append(f"下一刷：{format_refresh_ranges(next_ranges)}")
    return "\n".join(lines)


def format_refresh_ranges(ranges: Sequence[tuple[str, int, int]]) -> str:
    if not ranges:
        return "无"
    return "、".join(f"{reason}:{start}-{end}" for reason, start, end in ranges)


def build_rank_page_cache_overview_message(
    entries: Sequence[
        tuple[str, GlobalRankSpec, Sequence[Any], Sequence[Any], int, str]
    ],
) -> str:
    lines = ["📦【榜单页缓存】"]
    if not entries:
        lines.append("没有配置可刷新的全服榜。")
        return "\n".join(lines)

    lines.append("图例：█ 新鲜完整｜▓ 过期｜▒ 部分｜░ 缺失（左侧为第 1 名）")
    for _rank_key, spec, pages, targets, target_limit, _target_label in entries:
        coverage = _rank_page_coverage(pages, target_count=target_limit)
        next_text = "无"
        if targets:
            next_target = targets[0]
            next_text = (
                f"{next_target.reason}:"
                f"{next_target.start_rank}-{next_target.end_rank}"
            )
        title = spec.title if spec.title.endswith("榜") else f"{spec.title}榜"
        lines.append(
            f"{title}：[{_progress_bar(coverage, width=_PROGRESS_WIDTH)}] "
            f"{coverage.stored_count}/{target_limit} 名"
            f"（{_percentage(coverage.stored_count, target_limit)}）"
            f"｜下一刷 {next_text}"
        )
    return "\n".join(lines)


def build_rank_page_refresh_start_message(
    command: RankPageCacheRefreshCommand,
) -> str:
    if command.rank_key is None:
        return "🔄 正在刷新榜单页缓存。"
    return f"🔄 正在刷新{GLOBAL_RANKS[command.rank_key].title}缓存。"


def build_rank_page_refresh_result_message(result: Any) -> str:
    if result.total <= 0:
        return "✅【榜单页缓存刷新】当前没有缺失、部分缺失或过期页面。"

    lines = [
        "✅【榜单页缓存刷新完成】",
        f"本轮目标页面：{result.total} 页",
        f"成功刷新：{result.success} 页",
        f"失败：{result.failed} 页",
    ]
    if result.refreshed:
        shown = result.refreshed[:10]
        lines.append("")
        lines.append("刷新区间：")
        lines.extend(
            f"- {target.spec.title} "
            f"{target.reason}:{target.start_rank}-{target.end_rank}"
            for target in shown
        )
        if len(result.refreshed) > len(shown):
            lines.append(f"...另 {len(result.refreshed) - len(shown)} 页")
    if result.failures:
        lines.append("")
        lines.append("失败示例：")
        lines.extend(
            f"- {failure.target.spec.title} "
            f"{failure.target.start_rank}-{failure.target.end_rank}: {failure.reason}"
            for failure in result.failures[:5]
        )
    return "\n".join(lines)
