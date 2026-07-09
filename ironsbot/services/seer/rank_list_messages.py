# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.rank_list_formatting import (
    format_rank_intervals,
    format_rank_window,
    merge_rank_intervals,
    now_text,
    page_cache_rank_interval,
)
from ironsbot.services.seer.rank_list_models import (
    GLOBAL_RANKS,
    RANK_LIST_SIZE,
    GlobalRankSpec,
    LocalRankSpec,
    RankCacheBatchCommand,
    RankPageCacheRefreshCommand,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

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


def format_local_rank_message(  # noqa: PLR0913
    spec: LocalRankSpec,
    entries: Sequence[Any],
    *,
    sample_count: int,
    timestamp: str | None = None,
    season_sub_key: str | None = None,
    start_rank: int = 1,
    requested_count: int = RANK_LIST_SIZE,
) -> str:
    if not entries:
        return f"❌暂无{spec.title}数据。先查询一些米米号后再试。"

    range_text = format_rank_window(start_rank, len(entries), requested_count)
    if range_text:
        title = (
            f"{spec.title}（{range_text}，样本{sample_count}人，"
            f"截至{timestamp or now_text()}）"
        )
    else:
        title = f"{spec.title}（样本{sample_count}人，截至{timestamp or now_text()}）"
    if season_sub_key is not None:
        title += f"\n赛季样本：{season_sub_key}"

    lines = [title]
    lines.extend(
        f"{entry.rank}. {entry.nick}（{entry.user_id}） {entry.display}"
        for entry in entries
    )
    return "\n".join(lines)


def build_rank_batch_no_players_message(spec: GlobalRankSpec) -> str:
    return f"❌ 没有从{spec.title}拿到可缓存的榜单数据。"


def build_rank_batch_start_message(
    spec: GlobalRankSpec,
    command: RankCacheBatchCommand,
    *,
    item_count: int,
    requested_count: int,
) -> str:
    truncated_text = ""
    if requested_count > item_count:
        truncated_text = (
            "\n本次按 seer.local_rank.batch_limit "
            f"只处理前 {item_count} 个。"
        )

    return (
        f"🔄 正在缓存{spec.title}第 {command.start_rank}-{command.end_rank} 名。"
        f"\n实际拿到 {item_count} 条榜单数据。"
        "\n只写入全服榜单页缓存，不计入样本。"
        f"{truncated_text}"
    )


def build_rank_batch_result_message(
    spec: GlobalRankSpec,
    command: RankCacheBatchCommand,
    *,
    item_count: int,
    requested_count: int,
) -> str:
    truncated_text = ""
    if requested_count > item_count:
        truncated_text = f"\n本次实际缓存：{item_count}/{requested_count} 条"

    lines = [
        "✅【榜单区间缓存完成】",
        f"榜单：{spec.title}",
        f"请求区间：第 {command.start_rank}-{command.end_rank} 名",
        f"写入榜单页缓存：{item_count} 条",
        "样本缓存：未写入",
    ]
    if truncated_text:
        lines.append(truncated_text.strip())
    return "\n".join(lines)


def build_local_rank_cache_status_message(  # noqa: PLR0913
    stats: Any,
    *,
    rank_limit: int,
    batch_limit: int,
    refresh_limit: int,
    refresh_max_age_hours: int,
    display_limit: int = RANK_LIST_SIZE,
) -> str:
    lines = [
        "📊【样本榜缓存状态】",
        f"已缓存米米号：{stats.player_count}/{stats.max_players} 个",
        f"总缓存玩家：{stats.total_player_count} 个"
        "（含全服榜单扫到但未计入样本的人）",
        f"全服排行扫描上限：前 {rank_limit} 名",
        f"单次批量缓存上限：{batch_limit} 个",
        f"单轮刷新上限：{refresh_limit} 个",
        f"刷新过期时间：{refresh_max_age_hours} 小时",
        "巅峰样本：按当前赛季单独比较",
        f"榜单命令展示：前 {display_limit} 名",
        "",
        "可参与排行人数：",
    ]
    lines.extend(
        f"{title}：{count}"
        for title, count in stats.metric_counts.items()
    )
    return "\n".join(lines)


def build_local_rank_refresh_empty_message() -> str:
    return "❌ 当前没有本地样本缓存。先查询一些米米号后再刷新。"


def build_local_rank_refresh_start_message(
    before_stats: Any,
    *,
    refresh_limit: int,
    refresh_max_age_hours: int,
) -> str:
    return (
        "🔄 正在刷新样本榜缓存。"
        f"样本共 {before_stats.player_count} 个，本轮按最旧优先最多刷新 "
        f"{refresh_limit} 个，"
        "只刷新超过 "
        f"{refresh_max_age_hours} "
        "小时未更新的数据。"
    )


def build_local_rank_refresh_result_message(
    result: Any,
    after_stats: Any,
    *,
    failure_lines: Sequence[str] = (),
) -> str:
    lines = [
        "✅【样本榜缓存刷新完成】",
        f"本轮候选米米号：{result.total} 个",
        f"成功刷新：{result.success} 个",
        f"缓存已满跳过：{result.skipped_full} 个",
        f"失败：{result.failed} 个",
        f"当前缓存米米号：{after_stats.player_count}/{after_stats.max_players} 个",
    ]
    if failure_lines:
        lines.append("")
        lines.append("失败示例：")
        lines.extend(failure_lines)
    return "\n".join(lines)
