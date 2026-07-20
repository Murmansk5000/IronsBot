# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, bind_async
from ironsbot.runtime.permissions import can_manage_group_event
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import no_reply
from ironsbot.services.seer.rank_display import parse_rank_display_limit_command
from ironsbot.services.seer.rank_list_parsing import (
    parse_rank_cache_batch_command,
    parse_rank_list_command,
    parse_rank_page_cache_refresh_command,
    parse_rank_page_cache_status_command,
    parse_rank_player_command,
    parse_rank_score_command,
    with_admin_prefix,
)
from ironsbot.services.seer.rank_usage import RANK_HELP_DETAIL_COMMANDS

from ..group import SeerMatcherGroup, seer_feature_rule
from .rank_list_context import (
    RANK_CACHE_BATCH_COMMAND_KEY,
    RANK_DISPLAY_LIMIT_COMMAND_KEY,
    RANK_LIST_COMMAND_KEY,
    RANK_PAGE_CACHE_REFRESH_COMMAND_KEY,
    RANK_PAGE_CACHE_STATUS_COMMAND_KEY,
    RANK_PLAYER_COMMAND_KEY,
    RANK_SCORE_COMMAND_KEY,
    event_group_id,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot.adapters import Event
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

    from ironsbot.core.features import FeatureService
    from ironsbot.services.seer.rank_admin import RankAdminService
    from ironsbot.services.seer.rank_queries import RankQueryService

    PriorityRelease = Callable[[dict[str, object]], Awaitable[None]]


def _is_rank_list_command(
    service: RankQueryService,
    event: Event,
    state: T_State,
) -> bool:
    command = parse_rank_list_command(
        event.get_plaintext(),
        default_limit=service.default_limit(event_group_id(event)),
    )
    if command is None:
        return False
    state[RANK_LIST_COMMAND_KEY] = command
    return True


def _store_command(
    parser: Callable[[str], object | None],
    state_key: str,
    event: Event,
    state: T_State,
) -> bool:
    command = parser(event.get_plaintext())
    if command is None:
        return False
    state[state_key] = command
    return True


async def _handle_help(
    service: RankQueryService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(matcher, event, service.help_message())


async def _handle_list(
    service: RankQueryService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    message = await service.list(state[RANK_LIST_COMMAND_KEY])
    await finish_event_reply(matcher, event, message)


async def _handle_score(
    service: RankQueryService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    message = await service.score(
        state[RANK_SCORE_COMMAND_KEY],
        group_id=event_group_id(event),
    )
    await finish_event_reply(matcher, event, message)


async def _handle_player(
    service: RankQueryService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    message = await service.player(state[RANK_PLAYER_COMMAND_KEY])
    await finish_event_reply(matcher, event, message)


async def _progress(
    matcher: Matcher,
    event: MessageEvent,
    message: str,
) -> None:
    await send_event_reply(matcher, event, message)


async def _release(
    release_priority: PriorityRelease,
    state: T_State,
) -> None:
    await release_priority(state)


async def _handle_cache_batch(
    service: RankAdminService,
    release_priority: PriorityRelease,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    message = await service.cache_batch(
        state[RANK_CACHE_BATCH_COMMAND_KEY],
        progress=partial(_progress, matcher, event),
        release=partial(_release, release_priority, state),
    )
    await finish_event_reply(matcher, event, message)


async def _handle_page_status(
    service: RankAdminService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await finish_event_reply(
        matcher,
        event,
        service.page_status(state[RANK_PAGE_CACHE_STATUS_COMMAND_KEY]),
    )


async def _handle_page_overview(
    service: RankAdminService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(matcher, event, service.page_overview())


async def _handle_page_refresh(
    service: RankAdminService,
    release_priority: PriorityRelease,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    message = await service.page_refresh(
        state[RANK_PAGE_CACHE_REFRESH_COMMAND_KEY],
        progress=partial(_progress, matcher, event),
        release=partial(_release, release_priority, state),
    )
    await finish_event_reply(matcher, event, message)


async def _handle_cache_status(
    service: RankAdminService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(
        matcher,
        event,
        service.cache_status(event_group_id(event)),
    )


async def _handle_cache_refresh(
    service: RankAdminService,
    release_priority: PriorityRelease,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    message = await service.cache_refresh(
        progress=partial(_progress, matcher, event),
        release=partial(_release, release_priority, state),
    )
    await finish_event_reply(matcher, event, message)


async def _handle_display_limit(
    service: RankQueryService,
    features: FeatureService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    group_id = event_group_id(event)
    message = service.set_display_limit(
        group_id=group_id,
        user_id=int(event.user_id),
        can_manage=(
            isinstance(event, GroupMessageEvent)
            and can_manage_group_event(features, event)
        ),
        limit=int(state[RANK_DISPLAY_LIMIT_COMMAND_KEY]),
    )
    await finish_event_reply(matcher, event, message)


def install(group: SeerMatcherGroup) -> None:
    query = group.resources.rank_queries
    admin = group.resources.rank_admin
    feature_rule = seer_feature_rule(group.features, "seer_rank") & no_reply()
    priority = group.matcher_priority("seer_rank")

    help_matcher = group.on_fullmatch(
        RANK_HELP_DETAIL_COMMANDS,
        policy=CommandPolicy.command("seer_rank_help"),
        rule=feature_rule,
        priority=group.matcher_priority("seer_rank_help"),
    )
    help_matcher.append_handler(bind_async(_handle_help, query))

    list_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_list"),
        rule=feature_rule
        & Rule(partial(_is_rank_list_command, query)),
        priority=priority,
    )
    list_matcher.append_handler(bind_async(_handle_list, query))

    player_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_player"),
        rule=feature_rule
        & Rule(
            partial(
                _store_command,
                parse_rank_player_command,
                RANK_PLAYER_COMMAND_KEY,
            )
        ),
        priority=priority,
    )
    player_matcher.append_handler(bind_async(_handle_player, query))

    score_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_score"),
        rule=feature_rule
        & Rule(
            partial(
                _store_command,
                parse_rank_score_command,
                RANK_SCORE_COMMAND_KEY,
            )
        ),
        priority=priority,
    )
    score_matcher.append_handler(bind_async(_handle_score, query))

    cache_status = group.on_fullmatch(
        with_admin_prefix(("样本情况", "样本状态")),
        policy=CommandPolicy.command("seer_rank_cache_status"),
        rule=feature_rule,
        permission=SUPERUSER,
        priority=priority,
    )
    cache_status.append_handler(bind_async(_handle_cache_status, admin))

    cache_refresh = group.on_fullmatch(
        with_admin_prefix(("刷新样本",)),
        policy=CommandPolicy.command("seer_rank_cache_refresh"),
        rule=feature_rule,
        permission=SUPERUSER,
        priority=priority,
    )
    cache_refresh.append_handler(
        bind_async(
            _handle_cache_refresh,
            admin,
            group.release_priority,
        )
    )

    cache_batch = group.on_message(
        policy=CommandPolicy.command("seer_rank_cache_batch"),
        rule=feature_rule
        & Rule(
            partial(
                _store_command,
                parse_rank_cache_batch_command,
                RANK_CACHE_BATCH_COMMAND_KEY,
            )
        ),
        permission=SUPERUSER,
        priority=priority,
    )
    cache_batch.append_handler(
        bind_async(_handle_cache_batch, admin, group.release_priority)
    )

    page_overview = group.on_fullmatch(
        with_admin_prefix(("榜单情况", "榜单状态")),
        policy=CommandPolicy.command("seer_rank_page_cache_status"),
        rule=feature_rule,
        permission=SUPERUSER,
        priority=priority,
    )
    page_overview.append_handler(bind_async(_handle_page_overview, admin))

    page_status = group.on_message(
        policy=CommandPolicy.command("seer_rank_page_cache_status"),
        rule=feature_rule
        & Rule(
            partial(
                _store_command,
                parse_rank_page_cache_status_command,
                RANK_PAGE_CACHE_STATUS_COMMAND_KEY,
            )
        ),
        permission=SUPERUSER,
        priority=priority,
    )
    page_status.append_handler(bind_async(_handle_page_status, admin))

    page_refresh = group.on_message(
        policy=CommandPolicy.command("seer_rank_page_cache_refresh"),
        rule=feature_rule
        & Rule(
            partial(
                _store_command,
                parse_rank_page_cache_refresh_command,
                RANK_PAGE_CACHE_REFRESH_COMMAND_KEY,
            )
        ),
        permission=SUPERUSER,
        priority=priority,
    )
    page_refresh.append_handler(
        bind_async(_handle_page_refresh, admin, group.release_priority)
    )

    display_limit = group.on_message(
        policy=CommandPolicy.command("seer_rank_display_limit"),
        rule=feature_rule
        & Rule(
            partial(
                _store_command,
                parse_rank_display_limit_command,
                RANK_DISPLAY_LIMIT_COMMAND_KEY,
            )
        ),
        priority=priority,
    )
    display_limit.append_handler(
        bind_async(_handle_display_limit, query, group.features)
    )
