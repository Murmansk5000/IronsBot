# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.packets import ensure_extended_packets
from ironsbot.services.seer.rank_cache_messages import (
    build_local_rank_cache_status_message,
    build_local_rank_refresh_empty_message,
    build_local_rank_refresh_result_message,
    build_local_rank_refresh_start_message,
    build_rank_batch_no_players_message,
    build_rank_batch_result_message,
    build_rank_batch_start_message,
)
from ironsbot.services.seer.rank_list_spec_resolution import get_global_rank_spec
from ironsbot.services.seer.rank_page_cache_messages import (
    build_rank_page_cache_overview_message,
    build_rank_page_cache_status_message,
    build_rank_page_refresh_result_message,
    build_rank_page_refresh_start_message,
)
from ironsbot.services.seer.rank_page_cache_queries import get_rank_page_cache_summary
from ironsbot.services.seer.rank_page_refresh_selection import (
    configured_rank_specs,
    filter_standard_rank_page_summaries,
    rank_refresh_target_label,
)
from ironsbot.shared.messaging import finish_event_reply, send_event_reply

from .rank_list_actions import cache_global_rank_batch
from .rank_list_context import (
    RANK_CACHE_BATCH_COMMAND_KEY,
    RANK_PAGE_CACHE_REFRESH_COMMAND_KEY,
    RANK_PAGE_CACHE_STATUS_COMMAND_KEY,
    event_group_id,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

    from ironsbot.integrations.headless_seer.game import SeerGame
    from ironsbot.services.seer.rank_list_models import (
        RankCacheBatchCommand,
        RankPageCacheRefreshCommand,
        RankPageCacheStatusCommand,
    )
    from ironsbot.services.seer.resources import SeerQueryResources


async def handle_cache_batch(
    resources: SeerQueryResources,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    game: SeerGame,
) -> None:
    ensure_extended_packets()
    command: RankCacheBatchCommand = state[RANK_CACHE_BATCH_COMMAND_KEY]
    spec, item_count, requested_count = await cache_global_rank_batch(
        game,
        command,
        batch_limit=resources.config.local_rank.batch_limit,
    )
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
    await resources.priority.release(state)

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


async def handle_page_cache_status(
    resources: SeerQueryResources,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    command: RankPageCacheStatusCommand = state[RANK_PAGE_CACHE_STATUS_COMMAND_KEY]
    spec = get_global_rank_spec(command.rank_key)
    refresh = resources.rank_page_refresh
    pages = filter_standard_rank_page_summaries(
        spec,
        get_rank_page_cache_summary(key=spec.key, sub_key=spec.sub_key),
        config=refresh.config,
        rank_key=command.rank_key,
    )
    targets = refresh.preview([command.rank_key])
    rank_config = resources.config.rank
    await finish_event_reply(
        matcher,
        event,
        build_rank_page_cache_status_message(
            spec,
            pages,
            ttl_seconds=rank_config.page_cache_ttl_seconds,
            target_limit=rank_refresh_target_label(
                refresh.config,
                command.rank_key,
            ),
            next_ranges=[
                (target.reason, target.start_rank, target.end_rank)
                for target in targets[:5]
            ],
        ),
    )


async def handle_page_cache_overview(
    resources: SeerQueryResources,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    refresh = resources.rank_page_refresh
    specs = configured_rank_specs(refresh.config)
    targets = refresh.preview()
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
                config=refresh.config,
                rank_key=rank_key,
            ),
            targets_by_rank.get(rank_key, ()),
            rank_refresh_target_label(refresh.config, rank_key),
        )
        for rank_key, spec in specs
    ]
    await finish_event_reply(
        matcher,
        event,
        build_rank_page_cache_overview_message(entries),
    )


async def handle_page_cache_refresh(
    resources: SeerQueryResources,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    game: SeerGame,
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
    await resources.priority.release(state)
    rank_keys = None if command.rank_key is None else [command.rank_key]
    result = await resources.rank_page_refresh.refresh(game, rank_keys)
    await finish_event_reply(
        matcher,
        event,
        build_rank_page_refresh_result_message(result),
    )


async def handle_cache_status(
    resources: SeerQueryResources,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    stats = resources.local_rank.stats()
    await finish_event_reply(
        matcher,
        event,
        build_local_rank_cache_status_message(
            stats,
            rank_limit=resources.config.rank.limit,
            batch_limit=resources.config.local_rank.batch_limit,
            refresh_limit=resources.config.local_rank.refresh_limit,
            refresh_max_age_hours=resources.config.local_rank.refresh_max_age_hours,
            display_limit=resources.rank_display.limit_for_group(event_group_id(event)),
        ),
    )


async def handle_cache_refresh(
    resources: SeerQueryResources,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    game: SeerGame,
) -> None:
    ensure_extended_packets()
    before = resources.local_rank.stats()
    if before.player_count <= 0:
        await finish_event_reply(
            matcher,
            event,
            build_local_rank_refresh_empty_message(),
        )

    local_rank_config = resources.config.local_rank
    await send_event_reply(
        matcher,
        event,
        build_local_rank_refresh_start_message(
            before,
            refresh_limit=local_rank_config.refresh_limit,
            refresh_max_age_hours=local_rank_config.refresh_max_age_hours,
        ),
    )
    await resources.priority.release(state)
    result = await resources.local_rank.refresh(game)
    after = resources.local_rank.stats()

    await finish_event_reply(
        matcher,
        event,
        build_local_rank_refresh_result_message(
            result,
            after,
        ),
    )
