# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from ironsbot.services.admin_priority import release_superuser_priority
from ironsbot.services.seer.local_rank_cache_queries import get_local_rank_cache_stats
from ironsbot.services.seer.local_rank_refresh import (
    format_refresh_failures,
    refresh_local_rank_cache,
)
from ironsbot.services.seer.packets import ensure_extended_packets
from ironsbot.services.seer.rank_display import (
    build_rank_display_limit_denied_message,
    build_rank_display_limit_invalid_message,
    build_rank_display_limit_message,
    rank_display_limit_for_group,
    set_group_rank_display_limit,
)
from ironsbot.services.seer.rank_list_messages import (
    build_local_rank_cache_status_message,
    build_local_rank_refresh_empty_message,
    build_local_rank_refresh_result_message,
    build_local_rank_refresh_start_message,
    build_rank_batch_no_players_message,
    build_rank_batch_result_message,
    build_rank_batch_start_message,
    build_rank_page_cache_overview_message,
    build_rank_page_cache_status_message,
    build_rank_page_refresh_result_message,
    build_rank_page_refresh_start_message,
)
from ironsbot.services.seer.rank_list_models import (
    GLOBAL_RANKS,
    LOCAL_RANKS,
    RankCacheBatchCommand,
    RankListCommand,
    RankPageCacheRefreshCommand,
    RankPageCacheStatusCommand,
    RankScoreCommand,
)
from ironsbot.services.seer.rank_page_cache_queries import get_rank_page_cache_summary
from ironsbot.services.seer.rank_page_refresh import (
    configured_rank_specs,
    filter_standard_rank_page_summaries,
    preview_rank_page_refresh_targets,
    rank_refresh_target_label,
    refresh_rank_page_cache,
)
from ironsbot.services.seer.rank_usage import build_rank_help_message
from ironsbot.shared.features import is_superuser
from ironsbot.shared.messaging import (
    finish_event_reply,
    send_event_reply,
)
from ironsbot.shared.plugin_system import PluginContext, register_plugin

from ..config import get_local_rank_config, get_rank_query_config, get_seer_config
from .rank_list_actions import (
    build_global_rank_message,
    build_global_rank_score_message,
    build_local_rank_message,
    cache_global_rank_batch,
)

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

RANK_LIST_COMMAND_KEY = "_rank_list_command"
RANK_SCORE_COMMAND_KEY = "_rank_score_command"
RANK_CACHE_BATCH_COMMAND_KEY = "_rank_cache_batch_command"
RANK_PAGE_CACHE_STATUS_COMMAND_KEY = "_rank_page_cache_status_command"
RANK_PAGE_CACHE_REFRESH_COMMAND_KEY = "_rank_page_cache_refresh_command"
RANK_DISPLAY_LIMIT_COMMAND_KEY = "_rank_display_limit_command"
RANK_LIST_PLUGIN_NAME = "seer_rank_list"


class RankListPlugin:
    name = RANK_LIST_PLUGIN_NAME
    feature = "seer_rank"
    enabled = True

    async def handle(  # noqa: C901, PLR0911
        self,
        event: MessageEvent,
        context: PluginContext,
    ) -> None:
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
        if context.action == "score":
            await self._handle_score(matcher, event, state)
            return
        if context.action == "cache_batch":
            await self._handle_cache_batch(matcher, event, state)
            return
        if context.action == "page_cache_status":
            await self._handle_page_cache_status(matcher, event, state)
            return
        if context.action == "page_cache_overview":
            await self._handle_page_cache_overview(matcher, event)
            return
        if context.action == "page_cache_refresh":
            await self._handle_page_cache_refresh(matcher, event, state)
            return
        if context.action == "cache_status":
            await self._handle_cache_status(matcher, event)
            return
        if context.action == "cache_refresh":
            await self._handle_cache_refresh(matcher, event, state)
            return
        if context.action == "display_limit":
            await self._handle_display_limit(matcher, event, state)

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
                await build_global_rank_message(
                    GLOBAL_RANKS[command.rank_key],
                    command,
                ),
            )

        await finish_event_reply(
            matcher,
            event,
            build_local_rank_message(LOCAL_RANKS[command.rank_key], command),
        )

    async def _handle_score(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        command: RankScoreCommand = state[RANK_SCORE_COMMAND_KEY]
        await finish_event_reply(
            matcher,
            event,
            await build_global_rank_score_message(
                GLOBAL_RANKS[command.rank_key],
                command,
                display_limit=rank_display_limit_for_group(_event_group_id(event)),
            ),
        )

    async def _handle_cache_batch(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        ensure_extended_packets()
        command: RankCacheBatchCommand = state[RANK_CACHE_BATCH_COMMAND_KEY]
        spec, item_count, requested_count = await cache_global_rank_batch(command)
        if item_count <= 0:
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
                item_count=item_count,
                requested_count=requested_count,
            ),
        )
        await release_superuser_priority(state)

        await finish_event_reply(
            matcher,
            event,
            build_rank_batch_result_message(
                spec,
                command,
                item_count=item_count,
                requested_count=requested_count,
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
        pages = filter_standard_rank_page_summaries(
            spec,
            get_rank_page_cache_summary(key=spec.key, sub_key=spec.sub_key),
            rank_key=command.rank_key,
        )
        targets = preview_rank_page_refresh_targets([command.rank_key])
        refresh_config = get_rank_query_config().page_refresh
        await finish_event_reply(
            matcher,
            event,
            build_rank_page_cache_status_message(
                spec,
                pages,
                ttl_seconds=get_rank_query_config().page_cache_ttl_seconds,
                target_limit=rank_refresh_target_label(
                    refresh_config,
                    command.rank_key,
                ),
                next_ranges=[
                    (target.reason, target.start_rank, target.end_rank)
                    for target in targets[:5]
                ],
            ),
        )

    async def _handle_page_cache_overview(
        self,
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        rank_config = get_rank_query_config()
        specs = configured_rank_specs()
        targets = preview_rank_page_refresh_targets()
        targets_by_rank = {
            rank_key: [target for target in targets if target.rank_key == rank_key]
            for rank_key, _spec in specs
        }
        entries = [
            (
                rank_key,
                spec,
                filter_standard_rank_page_summaries(
                    spec,
                    get_rank_page_cache_summary(key=spec.key, sub_key=spec.sub_key),
                    rank_key=rank_key,
                ),
                targets_by_rank.get(rank_key, ()),
                rank_refresh_target_label(rank_config.page_refresh, rank_key),
            )
            for rank_key, spec in specs
        ]
        await finish_event_reply(
            matcher,
            event,
            build_rank_page_cache_overview_message(
                entries,
            ),
        )

    async def _handle_page_cache_refresh(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        ensure_extended_packets()
        command: RankPageCacheRefreshCommand = state[
            RANK_PAGE_CACHE_REFRESH_COMMAND_KEY
        ]
        await send_event_reply(
            matcher,
            event,
            build_rank_page_refresh_start_message(command),
        )
        await release_superuser_priority(state)
        rank_keys = None if command.rank_key is None else [command.rank_key]
        result = await refresh_rank_page_cache(rank_keys)
        await finish_event_reply(
            matcher,
            event,
            build_rank_page_refresh_result_message(result),
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
                display_limit=rank_display_limit_for_group(_event_group_id(event)),
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

    async def _handle_display_limit(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        command = state[RANK_DISPLAY_LIMIT_COMMAND_KEY]
        if not isinstance(event, GroupMessageEvent):
            await finish_event_reply(matcher, event, "❌ 这个设置只能在群聊中修改。")
            return

        if not _can_manage_group_rank_display(event):
            await finish_event_reply(
                matcher,
                event,
                build_rank_display_limit_denied_message(),
            )
            return

        rank_config = get_rank_query_config()
        if command.limit < 1 or command.limit > rank_config.max_display_limit:
            await finish_event_reply(
                matcher,
                event,
                build_rank_display_limit_invalid_message(command.limit),
            )
            return

        set_group_rank_display_limit(
            int(event.group_id),
            int(event.user_id),
            command.limit,
        )
        await finish_event_reply(
            matcher,
            event,
            build_rank_display_limit_message(
                group_id=int(event.group_id),
                limit=command.limit,
            ),
        )


register_plugin(RankListPlugin())


def _event_group_id(event: Event) -> int | None:
    group_id = getattr(event, "group_id", None)
    return int(group_id) if group_id is not None else None


def _can_manage_group_rank_display(event: GroupMessageEvent) -> bool:
    if is_superuser(int(event.user_id)):
        return True
    role = getattr(getattr(event, "sender", None), "role", "")
    return role in {"owner", "admin"}
