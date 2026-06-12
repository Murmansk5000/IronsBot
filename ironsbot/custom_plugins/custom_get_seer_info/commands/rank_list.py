# SPDX-License-Identifier: GPL-3.0-or-later
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
    RANK_LIST_SIZE,
    GlobalRankSpec,
    LocalRankSpec,
    RankCacheBatchCommand,
    RankListCommand,
    RankPageCacheStatusCommand,
    batch_raw_start,
    build_local_rank_cache_full_message,
    build_local_rank_cache_status_message,
    build_local_rank_refresh_empty_message,
    build_local_rank_refresh_result_message,
    build_local_rank_refresh_start_message,
    build_rank_batch_no_players_message,
    build_rank_batch_result_message,
    build_rank_batch_start_message,
    build_rank_page_cache_status_message,
    format_global_rank_message,
    format_local_rank_message,
    parse_rank_cache_batch_command,
    parse_rank_list_command,
    parse_rank_page_cache_status_command,
    with_admin_prefix,
)
from ironsbot.services.seer.rank_page_cache import get_rank_page_cache_summary
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


async def _build_global_rank_message(spec: GlobalRankSpec) -> str:
    game = get_game_client()
    items = await fetch_daily_rank_page(
        game,
        key=spec.key,
        sub_key=spec.sub_key,
        start=spec.start,
        count=RANK_LIST_SIZE,
    )
    return format_global_rank_message(spec, items)


async def _fetch_rank_batch_player_ids(
    command: RankCacheBatchCommand,
) -> tuple[GlobalRankSpec, list[int], int]:
    spec = GLOBAL_RANKS[command.rank_key]
    requested_count = command.end_rank - command.start_rank + 1
    count = min(requested_count, get_local_rank_config().batch_limit)
    raw_start = batch_raw_start(spec, command.start_rank)
    items = await fetch_daily_rank_page(
        get_game_client(),
        key=spec.key,
        sub_key=spec.sub_key,
        start=raw_start,
        count=count,
    )
    player_ids = [int(item.id) for item in items if int(item.id) > 0]
    return spec, player_ids, requested_count


def _build_local_rank_message(spec: LocalRankSpec) -> str:
    season_sub_key = get_current_peak_sub_key() if spec.season_limited else None
    entries, sample_count = get_local_rank_entries(
        spec.metric_key,
        limit=RANK_LIST_SIZE,
        season_sub_key=season_sub_key,
    )
    return format_local_rank_message(
        spec,
        entries,
        sample_count=sample_count,
        season_sub_key=season_sub_key,
    )


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
                build_local_rank_cache_full_message(before),
            )

        spec, player_ids, requested_count = await _fetch_rank_batch_player_ids(command)
        if not player_ids:
            await finish_event_reply(
                matcher,
                event,
                build_rank_batch_no_players_message(spec),
            )

        await send_event_reply(
            matcher,
            event,
            build_rank_batch_start_message(
                spec,
                command,
                before,
                player_id_count=len(player_ids),
                requested_count=requested_count,
            ),
        )
        await release_superuser_priority(state)
        result = await refresh_local_rank_cache(player_ids)
        after = get_local_rank_cache_stats()

        await finish_event_reply(
            matcher,
            event,
            build_rank_batch_result_message(
                spec,
                command,
                result,
                after,
                failure_lines=format_refresh_failures(result.failures),
            ),
        )

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
        pages = get_rank_page_cache_summary(key=spec.key, sub_key=spec.sub_key)
        await finish_event_reply(
            matcher,
            event,
            build_rank_page_cache_status_message(
                spec,
                pages,
                ttl_seconds=get_rank_query_config().page_cache_ttl_seconds,
            ),
        )

    async def _handle_cache_status(
        self,
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        stats = get_local_rank_cache_stats()
        query_config = get_seer_config()
        await finish_event_reply(
            matcher,
            event,
            build_local_rank_cache_status_message(
                stats,
                rank_limit=query_config.rank.limit,
                batch_limit=query_config.local_rank.batch_limit,
                refresh_limit=query_config.local_rank.refresh_limit,
                refresh_max_age_hours=(
                    query_config.local_rank.refresh_max_age_hours
                ),
            ),
        )

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
                build_local_rank_refresh_empty_message(),
            )

        local_rank_config = get_local_rank_config()
        await send_event_reply(
            matcher,
            event,
            build_local_rank_refresh_start_message(
                before,
                refresh_limit=local_rank_config.refresh_limit,
                refresh_max_age_hours=local_rank_config.refresh_max_age_hours,
            ),
        )
        await release_superuser_priority(state)
        result = await refresh_local_rank_cache()
        after = get_local_rank_cache_stats()

        await finish_event_reply(
            matcher,
            event,
            build_local_rank_refresh_result_message(
                result,
                after,
                failure_lines=format_refresh_failures(result.failures),
            ),
        )


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
