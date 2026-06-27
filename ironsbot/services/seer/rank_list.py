# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

from ironsbot.services.seer.rank_constants import (
    ACHIEVE_RANK_KEY,
    ACHIEVE_RANK_SUB_KEY,
    AUTOCARD_RANK_KEY,
    AUTOCARD_RANK_SUB_KEY,
    BOOK_RANK_KEY,
    BOOK_RANK_SUB_KEY,
    COUNTERMARK_RANK_KEY,
    COUNTERMARK_RANK_SUB_KEY,
    MOUNT_RANK_SUB_KEY,
    OUTFIT_PART_RANK_SUB_KEY,
    OUTFIT_RANK_KEY,
    OUTFIT_SUIT_RANK_SUB_KEY,
    PET_KIND_RANK_ANOMALY_COUNT,
    PET_KIND_RANK_KEY,
    PET_KIND_RANK_SUB_KEY,
    SKIN_RANK_KEY,
    SKIN_RANK_SUB_KEY,
)

RANK_LIST_SIZE = 10
RANK_LIST_MAX_SIZE = 100
BATCH_CACHE_PREFIXES = ("缓存榜单", "批量缓存榜单", "缓存排行", "批量缓存排行")
RANK_PAGE_CACHE_STATUS_PREFIXES = (
    "榜单情况",
    "榜单状态",
)
RANK_PAGE_CACHE_REFRESH_PREFIXES = (
    "刷新榜单",
)
MAX_CACHE_INTERVALS_SHOWN = 20


@dataclass(frozen=True, slots=True)
class GlobalRankSpec:
    title: str
    key: int
    sub_key: int
    unit: str
    start: int = 0
    rank_offset: int = 0


@dataclass(frozen=True, slots=True)
class LocalRankSpec:
    title: str
    metric_key: str
    season_limited: bool = False


@dataclass(frozen=True, slots=True)
class RankListCommand:
    kind: str
    rank_key: str
    start_rank: int = 1
    limit: int = RANK_LIST_SIZE


@dataclass(frozen=True, slots=True)
class RankCacheBatchCommand:
    rank_key: str
    start_rank: int
    end_rank: int


@dataclass(frozen=True, slots=True)
class RankPageCacheStatusCommand:
    rank_key: str


@dataclass(frozen=True, slots=True)
class RankPageCacheRefreshCommand:
    rank_key: str | None = None


GLOBAL_RANKS: dict[str, GlobalRankSpec] = {
    "图鉴积分": GlobalRankSpec("图鉴积分榜", BOOK_RANK_KEY, BOOK_RANK_SUB_KEY, "分"),
    "成就点数": GlobalRankSpec(
        "成就点数榜", ACHIEVE_RANK_KEY, ACHIEVE_RANK_SUB_KEY, "点"
    ),
    "精灵图鉴": GlobalRankSpec(
        "精灵图鉴榜",
        PET_KIND_RANK_KEY,
        PET_KIND_RANK_SUB_KEY,
        "项",
        start=PET_KIND_RANK_ANOMALY_COUNT,
        rank_offset=-PET_KIND_RANK_ANOMALY_COUNT,
    ),
    "皮肤图鉴": GlobalRankSpec("皮肤图鉴榜", SKIN_RANK_KEY, SKIN_RANK_SUB_KEY, "款"),
    "套装图鉴": GlobalRankSpec(
        "套装图鉴榜", OUTFIT_RANK_KEY, OUTFIT_SUIT_RANK_SUB_KEY, "套"
    ),
    "部件图鉴": GlobalRankSpec(
        "部件图鉴榜", OUTFIT_RANK_KEY, OUTFIT_PART_RANK_SUB_KEY, "件"
    ),
    "座驾图鉴": GlobalRankSpec("座驾图鉴榜", OUTFIT_RANK_KEY, MOUNT_RANK_SUB_KEY, "个"),
    "刻印图鉴": GlobalRankSpec(
        "刻印图鉴榜", COUNTERMARK_RANK_KEY, COUNTERMARK_RANK_SUB_KEY, "枚"
    ),
    "群星牌": GlobalRankSpec(
        "群星之巅榜", AUTOCARD_RANK_KEY, AUTOCARD_RANK_SUB_KEY, "分"
    ),
}

LOCAL_RANKS: dict[str, LocalRankSpec] = {
    "图鉴积分": LocalRankSpec("样本图鉴积分榜", "book_score"),
    "成就点数": LocalRankSpec("样本成就点数榜", "achievement_score"),
    "精灵数量": LocalRankSpec("样本精灵总数榜", "pet_total_count"),
    "精灵图鉴": LocalRankSpec("样本精灵图鉴榜", "pet_kind_count"),
    "皮肤图鉴": LocalRankSpec("样本皮肤图鉴榜", "skin_count"),
    "套装图鉴": LocalRankSpec("样本套装图鉴榜", "outfit_suit_count"),
    "部件图鉴": LocalRankSpec("样本部件图鉴榜", "outfit_part_count"),
    "座驾图鉴": LocalRankSpec("样本座驾图鉴榜", "mount_count"),
    "刻印图鉴": LocalRankSpec("样本刻印图鉴榜", "countermark_count"),
    "已解锁图鉴": LocalRankSpec("样本已解锁图鉴榜", "unlocked_book_entries"),
    "成就数量": LocalRankSpec("样本成就数量榜", "achievement_count"),
    "竞技段位": LocalRankSpec(
        "样本竞技段位榜", "peak_standard", season_limited=True
    ),
    "竞技胜率": LocalRankSpec(
        "样本竞技胜率榜", "peak_standard_win_rate", season_limited=True
    ),
    "竞技场次": LocalRankSpec(
        "样本竞技场次榜", "peak_standard_matches", season_limited=True
    ),
    "狂野段位": LocalRankSpec("样本狂野段位榜", "peak_wild", season_limited=True),
    "狂野胜率": LocalRankSpec(
        "样本狂野胜率榜", "peak_wild_win_rate", season_limited=True
    ),
    "狂野场次": LocalRankSpec(
        "样本狂野场次榜", "peak_wild_matches", season_limited=True
    ),
    "专家段位": LocalRankSpec("样本专家段位榜", "peak_expert", season_limited=True),
    "专家胜率": LocalRankSpec(
        "样本专家胜率榜", "peak_expert_win_rate", season_limited=True
    ),
    "专家场次": LocalRankSpec(
        "样本专家场次榜", "peak_expert_matches", season_limited=True
    ),
    "巅峰总场次": LocalRankSpec(
        "样本巅峰总场次榜", "peak_total_matches", season_limited=True
    ),
}


def with_admin_prefix(commands: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"/{command}" for command in commands)


def now_text() -> str:
    now = datetime.now(timezone(timedelta(hours=8)))
    return now.strftime("%Y-%m-%d %H:%M:%S")


def format_global_rank_line(
    item: Any,
    *,
    index: int,
    spec: GlobalRankSpec,
) -> str:
    rank = index + 1 + spec.rank_offset
    return f"{rank}. {item.nick}（{item.id}） {item.score}{spec.unit}"


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

    range_text = format_rank_window(start_rank, len(items), requested_count)
    if range_text:
        lines = [f"{spec.title}（{range_text}，截至{timestamp or now_text()}）"]
    else:
        lines = [f"{spec.title}（截至{timestamp or now_text()}）"]
    lines.extend(
        format_global_rank_line(
            item,
            index=batch_raw_start(spec, start_rank) + index,
            spec=spec,
        )
        for index, item in enumerate(items)
    )
    return "\n".join(lines)


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


def batch_raw_start(spec: GlobalRankSpec, start_rank: int) -> int:
    return max(spec.start, start_rank - 1 - spec.rank_offset)


def page_cache_rank_interval(
    page: Any,
    spec: GlobalRankSpec,
) -> tuple[int, int] | None:
    expected_count = int(getattr(page, "expected_count", page.item_count))
    if expected_count <= 0:
        return None

    start_rank = page.start_index + 1 + spec.rank_offset
    end_rank = page.start_index + expected_count + spec.rank_offset
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


def build_rank_page_cache_status_message(
    spec: GlobalRankSpec,
    pages: Sequence[Any],
    *,
    ttl_seconds: int,
    target_limit: int | None = None,
    next_ranges: Sequence[tuple[str, int, int]] = (),
) -> str:
    if not pages:
        lines = [f"📦【{spec.title}缓存】", "当前没有缓存区间。"]
        if target_limit is not None:
            lines.append(f"目标：前 {target_limit} 名")
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
    if target_limit is not None:
        lines.insert(1, f"目标：前 {target_limit} 名")
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
        tuple[str, GlobalRankSpec, Sequence[Any], Sequence[Any], int]
    ],
) -> str:
    lines = ["📦【榜单页缓存】"]
    if not entries:
        lines.append("没有配置可刷新的全服榜。")
        return "\n".join(lines)

    for _rank_key, spec, pages, targets, target_limit in entries:
        cached_count = sum(page.item_count for page in pages)
        partial_count = sum(1 for page in pages if getattr(page, "is_partial", False))
        stale_count = sum(1 for page in pages if getattr(page, "is_stale", False))
        next_text = "无"
        if targets:
            target = targets[0]
            next_text = f"{target.reason}:{target.start_rank}-{target.end_rank}"
        lines.append(
            f"{spec.title}：{cached_count}/{target_limit} 名，"
            f"部分 {partial_count} 页，过期 {stale_count} 页，下一刷 {next_text}"
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


def parse_rank_list_command(
    text: str,
    *,
    default_limit: int = RANK_LIST_SIZE,
    max_limit: int = RANK_LIST_MAX_SIZE,
) -> RankListCommand | None:
    command = _normalize_command_text(text)
    parsed = _match_rank_list_command(command)
    if parsed is None:
        return None

    kind, rank_key, suffix = parsed
    window = _parse_rank_window(
        suffix,
        default_limit=default_limit,
        max_limit=max_limit,
    )
    if window is None:
        return None

    start_rank, limit = window
    return RankListCommand(
        kind=kind,
        rank_key=rank_key,
        start_rank=start_rank,
        limit=limit,
    )


def parse_rank_cache_batch_command(text: str) -> RankCacheBatchCommand | None:
    stripped = _strip_command_prefix(text)
    if stripped is None:
        return None

    command = _normalize_command_text(stripped)
    normalized_prefix = _matching_normalized_prefix(command, BATCH_CACHE_PREFIXES)
    if normalized_prefix is None:
        return None

    command = command[len(normalized_prefix) :]
    match = re.fullmatch(r"(.+?)(\d+)(?:-|~|到|至)(\d+)", command)
    if match is None:
        return None

    rank_name, start_text, end_text = match.groups()
    rank_command = _NORMALIZED_COMMANDS.get(rank_name)
    start_rank = int(start_text)
    end_rank = int(end_text)

    if (
        rank_command is None
        or rank_command[0] != "global"
        or start_rank <= 0
        or end_rank < start_rank
    ):
        return None

    return RankCacheBatchCommand(
        rank_key=rank_command[1],
        start_rank=start_rank,
        end_rank=end_rank,
    )


def parse_rank_page_cache_status_command(
    text: str,
) -> RankPageCacheStatusCommand | None:
    stripped = _strip_command_prefix(text)
    if stripped is None:
        return None

    command = _normalize_command_text(stripped)
    normalized_prefix = _matching_normalized_prefix(
        command,
        RANK_PAGE_CACHE_STATUS_PREFIXES,
    )
    if normalized_prefix is None:
        return None

    rank_name = command[len(normalized_prefix) :]
    rank_command = _NORMALIZED_COMMANDS.get(rank_name)
    if rank_command is None or rank_command[0] != "global":
        return None

    return RankPageCacheStatusCommand(rank_key=rank_command[1])


def parse_rank_page_cache_refresh_command(
    text: str,
) -> RankPageCacheRefreshCommand | None:
    stripped = _strip_command_prefix(text)
    if stripped is None:
        return None

    command = _normalize_command_text(stripped)
    normalized_prefix = _matching_normalized_prefix(
        command,
        RANK_PAGE_CACHE_REFRESH_PREFIXES,
    )
    if normalized_prefix is None:
        return None

    rank_name = command[len(normalized_prefix) :]
    if not rank_name:
        return RankPageCacheRefreshCommand()

    rank_command = _NORMALIZED_COMMANDS.get(rank_name)
    if rank_command is None or rank_command[0] != "global":
        return None

    return RankPageCacheRefreshCommand(rank_key=rank_command[1])


def _build_command_map() -> dict[str, tuple[str, str]]:
    commands: dict[str, tuple[str, str]] = {}

    aliases = {
        "图鉴积分": ("图鉴积分榜", "图鉴榜"),
        "成就点数": ("成就点数榜", "成就榜"),
        "精灵图鉴": ("精灵图鉴榜", "精灵种类榜", "精灵榜"),
        "皮肤图鉴": ("皮肤图鉴榜", "皮肤榜"),
        "套装图鉴": ("套装图鉴榜", "套装榜"),
        "部件图鉴": ("部件图鉴榜", "部件榜"),
        "座驾图鉴": ("座驾图鉴榜", "座驾榜"),
        "刻印图鉴": ("刻印图鉴榜", "刻印榜"),
        "群星牌": ("群星牌榜", "群星之巅榜", "群星百强榜", "群星牌百强榜"),
    }
    for key, names in aliases.items():
        for name in names:
            commands[name] = ("global", key)

    local_aliases = {
        "精灵数量": (
            "精灵总数榜",
            "样本精灵数量榜",
            "样本精灵总数榜",
            "样品精灵数量榜",
            "样品精灵总数榜",
            "机器人精灵数量榜",
            "机器人精灵总数榜",
        ),
        "精灵图鉴": ("样本精灵榜", "机器人精灵榜"),
        "已解锁图鉴": ("样本已解锁图鉴榜", "机器人已解锁图鉴榜", "解锁图鉴榜"),
        "成就数量": ("样本成就数量榜", "机器人成就数量榜"),
        "竞技段位": ("样本竞技段位榜", "机器人竞技段位榜", "样本竞技榜"),
        "竞技胜率": ("样本竞技胜率榜", "机器人竞技胜率榜"),
        "竞技场次": ("样本竞技场次榜", "机器人竞技场次榜", "竞技场次榜"),
        "狂野段位": ("样本狂野段位榜", "机器人狂野段位榜", "样本狂野榜"),
        "狂野胜率": ("样本狂野胜率榜", "机器人狂野胜率榜"),
        "狂野场次": ("样本狂野场次榜", "机器人狂野场次榜", "狂野场次榜"),
        "专家段位": ("样本专家段位榜", "机器人专家段位榜", "样本专家榜"),
        "专家胜率": ("样本专家胜率榜", "机器人专家胜率榜"),
        "专家场次": ("样本专家场次榜", "机器人专家场次榜", "专家场次榜"),
        "巅峰总场次": (
            "样本场次榜",
            "样本场次总榜",
            "样本总场次榜",
            "样本巅峰场次榜",
            "样本巅峰总场次榜",
            "机器人场次榜",
            "机器人场次总榜",
            "机器人总场次榜",
            "场次榜",
            "场次总榜",
            "总场次榜",
        ),
    }
    for key, spec in GLOBAL_RANKS.items():
        if key not in LOCAL_RANKS:
            continue
        names = (
            f"样本{key}榜",
            f"机器人{key}榜",
            f"样本{spec.title}",
            f"机器人{spec.title}",
            *(f"样本{name}" for name in aliases.get(key, ())),
            *(f"机器人{name}" for name in aliases.get(key, ())),
        )
        local_aliases[key] = (*local_aliases.get(key, ()), *names)

    for key, names in local_aliases.items():
        for name in names:
            commands[name] = ("local", key)

    return commands


def _normalize_command_text(text: str) -> str:
    return "".join(text.split()).lower()


def _match_rank_list_command(command: str) -> tuple[str, str, str] | None:
    for prefix, value in sorted(
        _NORMALIZED_COMMANDS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if command.startswith(prefix):
            kind, rank_key = value
            return kind, rank_key, command[len(prefix) :]
    return None


def _parse_rank_window(  # noqa: PLR0911
    suffix: str,
    *,
    default_limit: int = RANK_LIST_SIZE,
    max_limit: int = RANK_LIST_MAX_SIZE,
) -> tuple[int, int] | None:
    if not suffix:
        return 1, default_limit

    page_match = re.fullmatch(r"第?(\d+)页", suffix)
    if page_match is not None:
        page = int(page_match.group(1))
        if page <= 0:
            return None
        return (page - 1) * default_limit + 1, default_limit

    range_match = re.fullmatch(r"第?(\d+)(?:-|~|到|至)(\d+)名?", suffix)
    if range_match is not None:
        start_rank = int(range_match.group(1))
        end_rank = int(range_match.group(2))
        if start_rank <= 0 or end_rank < start_rank:
            return None
        return start_rank, min(end_rank - start_rank + 1, max_limit)

    single_match = re.fullmatch(r"第?(\d+)名?", suffix)
    if single_match is not None:
        start_rank = int(single_match.group(1))
        if start_rank <= 0:
            return None
        return start_rank, 1

    return None


def _strip_command_prefix(text: str, prefixes: tuple[str, ...] = ("/",)) -> str | None:
    stripped = text.strip()
    for prefix in prefixes:
        if prefix and stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return None


def _matching_normalized_prefix(
    command: str,
    prefixes: tuple[str, ...],
) -> str | None:
    return next(
        (
            normalized_prefix
            for prefix in prefixes
            if command.startswith(
                normalized_prefix := _normalize_command_text(prefix)
            )
        ),
        None,
    )


_COMMANDS = _build_command_map()
_NORMALIZED_COMMANDS = {
    _normalize_command_text(command): value
    for command, value in _COMMANDS.items()
}
