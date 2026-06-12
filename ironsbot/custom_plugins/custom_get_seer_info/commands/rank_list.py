# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime, timedelta, timezone
from typing import Any

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.custom_plugins.message_actions import (
    finish_event_reply,
    send_event_reply,
)
from ironsbot.custom_plugins.superuser_priority import release_superuser_priority
from ironsbot.services.seer.client import get_game_client
from ironsbot.services.seer.local_rank import (
    get_local_rank_cache_stats,
    get_local_rank_entries,
)
from ironsbot.services.seer.local_rank_refresh import (
    format_refresh_failures,
    refresh_local_rank_cache,
)
from ironsbot.services.seer.packets import ensure_extended_packets
from ironsbot.services.seer.rank import (
    fetch_daily_rank_page,
    get_current_peak_sub_key,
)
from ironsbot.services.seer.rank_list import (
    GLOBAL_RANKS,
    LOCAL_RANKS,
    MAX_CACHE_INTERVALS_SHOWN,
    RANK_LIST_SIZE,
    GlobalRankSpec,
    LocalRankSpec,
    RankCacheBatchCommand,
    RankListCommand,
    RankPageCacheStatusCommand,
    parse_rank_cache_batch_command,
    parse_rank_list_command,
    parse_rank_page_cache_status_command,
    with_admin_prefix,
)
from ironsbot.services.seer.rank_page_cache import (
    CachedRankPageSummary,
    get_rank_page_cache_summary,
)
from ironsbot.services.seer.rank_usage import build_rank_help_message
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

from ..config import get_local_rank_config, get_rank_query_config, get_seer_config
from ..group import matcher_group

RANK_LIST_COMMAND_KEY = "_rank_list_command"
RANK_CACHE_BATCH_COMMAND_KEY = "_rank_cache_batch_command"
RANK_PAGE_CACHE_STATUS_COMMAND_KEY = "_rank_page_cache_status_command"
RANK_LIST_PLUGIN_NAME = "seer_rank_list"


async def _is_rank_list_command(event: Event, state: T_State) -> bool:
    command = parse_rank_list_command(event.get_plaintext())
    if command is None:
        return False

    state[RANK_LIST_COMMAND_KEY] = command
    return True


async def _is_rank_cache_batch_command(event: Event, state: T_State) -> bool:
    command = parse_rank_cache_batch_command(event.get_plaintext())
    if command is None:
        return False

    state[RANK_CACHE_BATCH_COMMAND_KEY] = command
    return True


async def _is_rank_page_cache_status_command(event: Event, state: T_State) -> bool:
    command = parse_rank_page_cache_status_command(event.get_plaintext())
    if command is None:
        return False

    state[RANK_PAGE_CACHE_STATUS_COMMAND_KEY] = command
    return True


rank_help_matcher = matcher_group.on_fullmatch(
    ("榜单帮助", "排行榜帮助", "有哪些榜单", "可用榜单"),
    rule=no_reply(),
)
rank_list_matcher = matcher_group.on_message(
    rule=Rule(_is_rank_list_command) & no_reply(),
)
rank_cache_status_matcher = matcher_group.on_fullmatch(
    with_admin_prefix((
        "缓存情况",
        "缓存状态",
        "查询缓存",
        "样本缓存",
        "样本榜状态",
        "本地榜状态",
        "机器人样本状态",
    )),
    rule=no_reply(),
    permission=SUPERUSER,
)
rank_cache_refresh_matcher = matcher_group.on_fullmatch(
    with_admin_prefix(("更新样本榜", "刷新样本榜", "重建样本榜")),
    rule=no_reply(),
    permission=SUPERUSER,
)
rank_cache_batch_matcher = matcher_group.on_message(
    rule=Rule(_is_rank_cache_batch_command) & no_reply(),
    permission=SUPERUSER,
)
rank_page_cache_status_matcher = matcher_group.on_message(
    rule=Rule(_is_rank_page_cache_status_command) & no_reply(),
    permission=SUPERUSER,
)


def _now_text() -> str:
    now = datetime.now(timezone(timedelta(hours=8)))
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _format_global_line(
    item: Any,
    *,
    index: int,
    spec: GlobalRankSpec,
) -> str:
    rank = index + 1 + spec.rank_offset
    return f"{rank}. {item.nick}（{item.id}） {item.score}{spec.unit}"


async def _build_global_rank_message(spec: GlobalRankSpec) -> str:
    game = get_game_client()
    items = await fetch_daily_rank_page(
        game,
        key=spec.key,
        sub_key=spec.sub_key,
        start=spec.start,
        count=RANK_LIST_SIZE,
    )
    if not items:
        return f"❌找不到{spec.title}数据。"

    lines = [f"{spec.title}（截至{_now_text()}）"]
    lines.extend(
        _format_global_line(item, index=spec.start + index, spec=spec)
        for index, item in enumerate(items)
    )
    return "\n".join(lines)


def _batch_raw_start(spec: GlobalRankSpec, start_rank: int) -> int:
    return max(spec.start, start_rank - 1 - spec.rank_offset)


async def _fetch_rank_batch_player_ids(
    command: RankCacheBatchCommand,
) -> tuple[GlobalRankSpec, list[int], int]:
    spec = GLOBAL_RANKS[command.rank_key]
    requested_count = command.end_rank - command.start_rank + 1
    count = min(requested_count, get_local_rank_config().batch_limit)
    raw_start = _batch_raw_start(spec, command.start_rank)
    items = await fetch_daily_rank_page(
        get_game_client(),
        key=spec.key,
        sub_key=spec.sub_key,
        start=raw_start,
        count=count,
    )
    player_ids = [int(item.id) for item in items if int(item.id) > 0]
    return spec, player_ids, requested_count


def _page_cache_rank_interval(
    page: CachedRankPageSummary,
    spec: GlobalRankSpec,
) -> tuple[int, int] | None:
    if page.item_count <= 0:
        return None

    start_rank = page.start_index + 1 + spec.rank_offset
    end_rank = page.start_index + page.item_count + spec.rank_offset
    return max(1, start_rank), max(1, end_rank)


def _merge_rank_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
            continue

        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged


def _format_rank_intervals(intervals: list[tuple[int, int]]) -> str:
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


def _build_rank_page_cache_status_message(spec: GlobalRankSpec) -> str:
    pages = get_rank_page_cache_summary(key=spec.key, sub_key=spec.sub_key)
    if not pages:
        return f"📦【{spec.title}缓存】\n当前没有缓存区间。"

    valid_pages = [page for page in pages if not page.is_stale]
    stale_pages = [page for page in pages if page.is_stale]
    valid_intervals = _merge_rank_intervals(
        [
            interval
            for page in valid_pages
            if (interval := _page_cache_rank_interval(page, spec)) is not None
        ]
    )
    stale_intervals = _merge_rank_intervals(
        [
            interval
            for page in stale_pages
            if (interval := _page_cache_rank_interval(page, spec)) is not None
        ]
    )

    valid_count = sum(page.item_count for page in valid_pages)
    stale_count = sum(page.item_count for page in stale_pages)
    lines = [
        f"📦【{spec.title}缓存】",
        f"有效缓存：{len(valid_pages)} 段，{valid_count} 名",
        f"有效区间：{_format_rank_intervals(valid_intervals)}",
    ]
    if stale_pages:
        lines.extend(
            [
                f"过期缓存：{len(stale_pages)} 段，{stale_count} 名",
                f"过期区间：{_format_rank_intervals(stale_intervals)}",
            ]
        )
    ttl = get_rank_query_config().page_cache_ttl_seconds
    lines.append(f"TTL：{ttl} 秒")
    return "\n".join(lines)


def _build_local_rank_message(spec: LocalRankSpec) -> str:
    season_sub_key = get_current_peak_sub_key() if spec.season_limited else None
    entries, sample_count = get_local_rank_entries(
        spec.metric_key,
        limit=RANK_LIST_SIZE,
        season_sub_key=season_sub_key,
    )
    if not entries:
        return f"❌暂无{spec.title}数据。先查询一些米米号后再试。"

    title = f"{spec.title}（样本{sample_count}人，截至{_now_text()}）"
    if season_sub_key is not None:
        title += f"\n赛季样本：{season_sub_key}"

    lines = [title]
    lines.extend(
        f"{entry.rank}. {entry.nick}（{entry.user_id}） {entry.display}"
        for entry in entries
    )
    return "\n".join(lines)


class RankListPlugin:
    name = RANK_LIST_PLUGIN_NAME
    feature = "rank"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        matcher = context.matcher
        if matcher is None:
            return

        state = context.state if context.state is not None else {}
        if context.action == "help":
            await self._handle_help(matcher, event)
            return
        if context.action == "list":
            await self._handle_list(matcher, event, state)
            return
        if context.action == "cache_batch":
            await self._handle_cache_batch(matcher, event, state)
            return
        if context.action == "page_cache_status":
            await self._handle_page_cache_status(matcher, event, state)
            return
        if context.action == "cache_status":
            await self._handle_cache_status(matcher, event)
            return
        if context.action == "cache_refresh":
            await self._handle_cache_refresh(matcher, event, state)

    async def _handle_help(self, matcher: Matcher, event: MessageEvent) -> None:
        await finish_event_reply(matcher, event, build_rank_help_message())

    async def _handle_list(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        command: RankListCommand = state[RANK_LIST_COMMAND_KEY]

        if command.kind == "global":
            await finish_event_reply(
                matcher,
                event,
                await _build_global_rank_message(GLOBAL_RANKS[command.rank_key]),
            )

        await finish_event_reply(
            matcher,
            event,
            _build_local_rank_message(LOCAL_RANKS[command.rank_key]),
        )

    async def _handle_cache_batch(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        ensure_extended_packets()
        command: RankCacheBatchCommand = state[RANK_CACHE_BATCH_COMMAND_KEY]
        before = get_local_rank_cache_stats()
        if before.player_count >= before.max_players:
            await finish_event_reply(
                matcher,
                event,
                f"❌ 样本缓存已满：{before.player_count}/{before.max_players}。"
                "请先调大 seer.local_rank.max_players。",
            )

        spec, player_ids, requested_count = await _fetch_rank_batch_player_ids(command)
        if not player_ids:
            await finish_event_reply(
                matcher,
                event,
                f"❌ 没有从{spec.title}拿到可缓存的米米号。",
            )

        truncated_text = ""
        if requested_count > len(player_ids):
            truncated_text = (
                "\n本次按 seer.local_rank.batch_limit "
                f"只处理前 {len(player_ids)} 个。"
            )

        await send_event_reply(
            matcher,
            event,
            f"🔄 正在缓存{spec.title}第 {command.start_rank}-{command.end_rank} 名。"
            f"\n实际拿到 {len(player_ids)} 个米米号。"
            f"\n当前缓存：{before.player_count}/{before.max_players}。"
            f"{truncated_text}",
        )
        await release_superuser_priority(state)
        result = await refresh_local_rank_cache(player_ids)
        after = get_local_rank_cache_stats()

        lines = [
            "✅【榜单区间缓存完成】",
            f"榜单：{spec.title}",
            f"请求区间：第 {command.start_rank}-{command.end_rank} 名",
            f"本次处理：{result.total} 个",
            f"成功写入/刷新：{result.success} 个",
            f"缓存已满跳过：{result.skipped_full} 个",
            f"失败：{result.failed} 个",
            f"当前缓存：{after.player_count}/{after.max_players}",
        ]
        if result.failures:
            lines.append("")
            lines.append("失败示例：")
            lines.extend(format_refresh_failures(result.failures))

        await finish_event_reply(matcher, event, "\n".join(lines))

    async def _handle_page_cache_status(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        command: RankPageCacheStatusCommand = state[
            RANK_PAGE_CACHE_STATUS_COMMAND_KEY
        ]
        spec = GLOBAL_RANKS[command.rank_key]
        await finish_event_reply(
            matcher,
            event,
            _build_rank_page_cache_status_message(spec),
        )

    async def _handle_cache_status(
        self,
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        stats = get_local_rank_cache_stats()
        query_config = get_seer_config()
        lines = [
            "📊【样本榜缓存状态】",
            f"已缓存米米号：{stats.player_count}/{stats.max_players} 个",
            f"总缓存玩家：{stats.total_player_count} 个"
            "（含全服榜单扫到但未计入样本的人）",
            f"全服排行扫描上限：前 {query_config.rank.limit} 名",
            f"单次批量缓存上限：{query_config.local_rank.batch_limit} 个",
            f"单轮刷新上限：{query_config.local_rank.refresh_limit} 个",
            f"刷新过期时间：{query_config.local_rank.refresh_max_age_hours} 小时",
            "巅峰样本：按当前赛季单独比较",
            f"榜单命令展示：前 {RANK_LIST_SIZE} 名",
            "",
            "可参与排行人数：",
        ]
        lines.extend(
            f"{title}：{count}"
            for title, count in stats.metric_counts.items()
        )
        await finish_event_reply(matcher, event, "\n".join(lines))

    async def _handle_cache_refresh(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        ensure_extended_packets()
        before = get_local_rank_cache_stats()
        if before.player_count <= 0:
            await finish_event_reply(
                matcher,
                event,
                "❌ 当前没有本地样本缓存。先查询一些米米号后再刷新。",
            )

        await send_event_reply(
            matcher,
            event,
            "🔄 正在刷新样本榜缓存。"
            f"样本共 {before.player_count} 个，本轮按最旧优先最多刷新 "
            f"{get_local_rank_config().refresh_limit} 个，"
            "只刷新超过 "
            f"{get_local_rank_config().refresh_max_age_hours} "
            "小时未更新的数据。",
        )
        await release_superuser_priority(state)
        result = await refresh_local_rank_cache()
        after = get_local_rank_cache_stats()

        lines = [
            "✅【样本榜缓存刷新完成】",
            f"本轮候选米米号：{result.total} 个",
            f"成功刷新：{result.success} 个",
            f"缓存已满跳过：{result.skipped_full} 个",
            f"失败：{result.failed} 个",
            f"当前缓存米米号：{after.player_count}/{after.max_players} 个",
        ]
        if result.failures:
            lines.append("")
            lines.append("失败示例：")
            lines.extend(format_refresh_failures(result.failures))

        await finish_event_reply(matcher, event, "\n".join(lines))


register_plugin(RankListPlugin())


@rank_help_matcher.handle()
async def handle_rank_help(matcher: Matcher, event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=RANK_LIST_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="help",
    )


@rank_list_matcher.handle()
async def handle_rank_list(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=RANK_LIST_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="list",
    )


@rank_cache_batch_matcher.handle()
async def handle_rank_cache_batch(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=RANK_LIST_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="cache_batch",
    )


@rank_page_cache_status_matcher.handle()
async def handle_rank_page_cache_status(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=RANK_LIST_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="page_cache_status",
    )


@rank_cache_status_matcher.handle()
async def handle_rank_cache_status(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await dispatch_plugin(
        plugin_name=RANK_LIST_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="cache_status",
    )


@rank_cache_refresh_matcher.handle()
async def handle_rank_cache_refresh(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=RANK_LIST_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="cache_refresh",
    )
