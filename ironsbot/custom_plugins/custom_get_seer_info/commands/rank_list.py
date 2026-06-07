# SPDX-License-Identifier: GPL-3.0-or-later
import re
from dataclasses import dataclass
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
from ironsbot.utils.rule import no_reply

from ..config import plugin_config
from ..group import matcher_group
from ..packets import ensure_extended_packets
from ._client import get_game_client
from ._local_rank import get_local_rank_cache_stats, get_local_rank_entries
from ._local_rank_refresh import format_refresh_failures, refresh_local_rank_cache
from ._rank import (
    ACHIEVE_RANK_KEY,
    ACHIEVE_RANK_SUB_KEY,
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
    fetch_daily_rank_page,
    get_current_peak_sub_key,
)
from ._rank_page_cache import CachedRankPageSummary, get_rank_page_cache_summary
from .rank_usage import build_rank_help_message

RANK_LIST_SIZE = 20
RANK_LIST_COMMAND_KEY = "_rank_list_command"
RANK_CACHE_BATCH_COMMAND_KEY = "_rank_cache_batch_command"
RANK_PAGE_CACHE_STATUS_COMMAND_KEY = "_rank_page_cache_status_command"
BATCH_CACHE_PREFIXES = ("缓存榜单", "批量缓存榜单", "缓存排行", "批量缓存排行")
RANK_PAGE_CACHE_STATUS_PREFIXES = ("榜单缓存", "排行缓存", "全服榜缓存", "缓存区间")
ADMIN_COMMAND_PREFIX = "/"
MAX_CACHE_INTERVALS_SHOWN = 20


def _normalize_command_text(text: str) -> str:
    return "".join(text.split()).lower()


def _strip_admin_command_prefix(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith(ADMIN_COMMAND_PREFIX):
        return None

    return stripped[len(ADMIN_COMMAND_PREFIX) :].strip()


def _with_admin_prefix(commands: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{ADMIN_COMMAND_PREFIX}{command}" for command in commands)


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
class RankCacheBatchCommand:
    rank_key: str
    start_rank: int
    end_rank: int


@dataclass(frozen=True, slots=True)
class RankPageCacheStatusCommand:
    rank_key: str


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


COMMANDS = _build_command_map()
NORMALIZED_COMMANDS = {
    _normalize_command_text(command): value
    for command, value in COMMANDS.items()
}


async def _is_rank_list_command(event: Event, state: T_State) -> bool:
    command = _normalize_command_text(event.get_plaintext())
    if command not in NORMALIZED_COMMANDS:
        return False

    state[RANK_LIST_COMMAND_KEY] = command
    return True


def _parse_rank_cache_batch_command(text: str) -> RankCacheBatchCommand | None:
    stripped = _strip_admin_command_prefix(text)
    if stripped is None:
        return None

    command = _normalize_command_text(stripped)
    normalized_prefix = next(
        (
            _normalize_command_text(prefix)
            for prefix in BATCH_CACHE_PREFIXES
            if command.startswith(_normalize_command_text(prefix))
        ),
        None,
    )
    if normalized_prefix is None:
        return None

    command = command[len(normalized_prefix) :]
    match = re.fullmatch(r"(.+?)(\d+)(?:-|~|到|至)(\d+)", command)
    if match is not None:
        rank_name, start_text, end_text = match.groups()
        rank_command = NORMALIZED_COMMANDS.get(rank_name)
        start_rank = int(start_text)
        end_rank = int(end_text)

        if (
            rank_command is not None
            and rank_command[0] == "global"
            and start_rank > 0
            and end_rank >= start_rank
        ):
            return RankCacheBatchCommand(
                rank_key=rank_command[1],
                start_rank=start_rank,
                end_rank=end_rank,
            )

    return None


async def _is_rank_cache_batch_command(event: Event, state: T_State) -> bool:
    command = _parse_rank_cache_batch_command(event.get_plaintext())
    if command is None:
        return False

    state[RANK_CACHE_BATCH_COMMAND_KEY] = command
    return True


def _parse_rank_page_cache_status_command(
    text: str,
) -> RankPageCacheStatusCommand | None:
    stripped = _strip_admin_command_prefix(text)
    if stripped is None:
        return None

    command = _normalize_command_text(stripped)
    normalized_prefix = next(
        (
            _normalize_command_text(prefix)
            for prefix in RANK_PAGE_CACHE_STATUS_PREFIXES
            if command.startswith(_normalize_command_text(prefix))
        ),
        None,
    )
    if normalized_prefix is None:
        return None

    rank_name = command[len(normalized_prefix) :]
    rank_command = NORMALIZED_COMMANDS.get(rank_name)
    if rank_command is None or rank_command[0] != "global":
        return None

    return RankPageCacheStatusCommand(rank_key=rank_command[1])


async def _is_rank_page_cache_status_command(event: Event, state: T_State) -> bool:
    command = _parse_rank_page_cache_status_command(event.get_plaintext())
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
    _with_admin_prefix((
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
    _with_admin_prefix(("更新样本榜", "刷新样本榜", "重建样本榜")),
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
    count = min(requested_count, plugin_config.seer_query_cache_batch_limit)
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
    lines.append(f"TTL：{plugin_config.seer_query_rank_page_cache_ttl_seconds} 秒")
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


@rank_help_matcher.handle()
async def handle_rank_help(matcher: Matcher, event: MessageEvent) -> None:
    await finish_event_reply(matcher, event, build_rank_help_message())


@rank_list_matcher.handle()
async def handle_rank_list(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    command = state[RANK_LIST_COMMAND_KEY]
    kind, key = NORMALIZED_COMMANDS[command]

    if kind == "global":
        await finish_event_reply(
            matcher,
            event,
            await _build_global_rank_message(GLOBAL_RANKS[key]),
        )

    await finish_event_reply(
        matcher,
        event,
        _build_local_rank_message(LOCAL_RANKS[key]),
    )


@rank_cache_batch_matcher.handle()
async def handle_rank_cache_batch(
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
            "请先调大 SEER_QUERY_LOCAL_RANK_MAX_PLAYERS。"
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
            f"\n本次按 SEER_QUERY_CACHE_BATCH_LIMIT 只处理前 {len(player_ids)} 个。"
        )

    await send_event_reply(
        matcher,
        event,
        f"🔄 正在缓存{spec.title}第 {command.start_rank}-{command.end_rank} 名。"
        f"\n实际拿到 {len(player_ids)} 个米米号。"
        f"\n当前缓存：{before.player_count}/{before.max_players}。"
        f"{truncated_text}"
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


@rank_page_cache_status_matcher.handle()
async def handle_rank_page_cache_status(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    command: RankPageCacheStatusCommand = state[RANK_PAGE_CACHE_STATUS_COMMAND_KEY]
    spec = GLOBAL_RANKS[command.rank_key]
    await finish_event_reply(
        matcher,
        event,
        _build_rank_page_cache_status_message(spec),
    )


@rank_cache_status_matcher.handle()
async def handle_rank_cache_status(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    stats = get_local_rank_cache_stats()
    lines = [
        "📊【样本榜缓存状态】",
        f"已缓存米米号：{stats.player_count}/{stats.max_players} 个",
        f"总缓存玩家：{stats.total_player_count} 个（含全服榜单扫到但未计入样本的人）",
        f"全服排行扫描上限：前 {plugin_config.seer_query_rank_limit} 名",
        f"单次批量缓存上限：{plugin_config.seer_query_cache_batch_limit} 个",
        f"单轮刷新上限：{plugin_config.seer_query_cache_refresh_limit} 个",
        f"刷新过期时间：{plugin_config.seer_query_cache_refresh_max_age_hours} 小时",
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


@rank_cache_refresh_matcher.handle()
async def handle_rank_cache_refresh(
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
        f"{plugin_config.seer_query_cache_refresh_limit} 个，"
        "只刷新超过 "
        f"{plugin_config.seer_query_cache_refresh_max_age_hours} 小时未更新的数据。"
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
