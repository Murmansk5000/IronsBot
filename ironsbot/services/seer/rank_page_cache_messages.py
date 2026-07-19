# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

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


def build_rank_page_cache_status_message(
    spec: GlobalRankSpec,
    pages: Sequence[Any],
    *,
    ttl_seconds: int,
    target_limit: int | str | None = None,
    next_ranges: Sequence[tuple[str, int, int]] = (),
) -> str:
    target_text = (
        f"前 {target_limit} 名" if isinstance(target_limit, int) else target_limit
    )
    if not pages:
        lines = [f"📦【{spec.title}缓存】", "当前没有缓存区间。"]
        if target_text is not None:
            lines.append(f"目标：{target_text}")
        if next_ranges:
            lines.append(f"下一刷：{format_refresh_ranges(next_ranges)}")
        return "\n".join(lines)

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

    valid_count = sum(page.item_count for page in valid_pages)
    stale_count = sum(page.item_count for page in stale_pages)
    partial_count = sum(page.item_count for page in partial_pages)
    lines = [
        f"📦【{spec.title}缓存】",
        f"有效缓存：{len(valid_pages)} 段，{valid_count} 名",
        f"有效区间：{format_rank_intervals(valid_intervals)}",
    ]
    if target_text is not None:
        lines.insert(1, f"目标：{target_text}")
    if partial_pages:
        lines.extend(
            [
                f"部分缺失：{len(partial_pages)} 段，现存 {partial_count} 名",
                f"缺失区间：{format_rank_intervals(partial_intervals)}",
            ]
        )
    if stale_pages:
        lines.extend(
            [
                f"过期缓存：{len(stale_pages)} 段，{stale_count} 名",
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
        tuple[str, GlobalRankSpec, Sequence[Any], Sequence[Any], int | str]
    ],
) -> str:
    lines = ["📦【榜单页缓存】"]
    if not entries:
        lines.append("没有配置可刷新的全服榜。")
        return "\n".join(lines)

    for _rank_key, spec, pages, targets, target_label in entries:
        cached_count = sum(page.item_count for page in pages)
        partial_count = sum(1 for page in pages if getattr(page, "is_partial", False))
        stale_count = sum(1 for page in pages if getattr(page, "is_stale", False))
        next_text = "无"
        if targets:
            next_target = targets[0]
            next_text = (
                f"{next_target.reason}:"
                f"{next_target.start_rank}-{next_target.end_rank}"
            )
        if isinstance(target_label, int):
            prefix = f"{spec.title}：{cached_count}/{target_label} 名"
        else:
            prefix = f"{spec.title}：{cached_count} 名，目标 {target_label}"
        lines.append(
            f"{prefix}，部分 {partial_count} 页，"
            f"过期 {stale_count} 页，下一刷 {next_text}"
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
