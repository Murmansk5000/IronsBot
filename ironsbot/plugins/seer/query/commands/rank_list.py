# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Awaitable, Callable
from functools import partial

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.integrations.headless_seer.game import SeerGame
from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.services.seer.rank_display import (
    parse_rank_display_limit_command,
    rank_display_limit_for_group,
)
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
from ironsbot.utils.rule import no_reply

from ..group import SeerMatcherGroup, seer_feature_rule
from . import (
    rank_list_cache_handlers,
    rank_list_display_handlers,
    rank_list_query_handlers,
)
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

GameHandler = Callable[
    [Matcher, MessageEvent, T_State, SeerGame],
    Awaitable[None],
]


async def _is_rank_list_command(event: Event, state: T_State) -> bool:
    command = parse_rank_list_command(
        event.get_plaintext(),
        default_limit=rank_display_limit_for_group(event_group_id(event)),
    )
    if command is None:
        return False

    state[RANK_LIST_COMMAND_KEY] = command
    return True


async def _is_rank_score_command(event: Event, state: T_State) -> bool:
    command = parse_rank_score_command(event.get_plaintext())
    if command is None:
        return False

    state[RANK_SCORE_COMMAND_KEY] = command
    return True


async def _is_rank_player_command(event: Event, state: T_State) -> bool:
    command = parse_rank_player_command(event.get_plaintext())
    if command is None:
        return False

    state[RANK_PLAYER_COMMAND_KEY] = command
    return True


async def _is_rank_display_limit_command(event: Event, state: T_State) -> bool:
    command = parse_rank_display_limit_command(event.get_plaintext())
    if command is None:
        return False

    state[RANK_DISPLAY_LIMIT_COMMAND_KEY] = command
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


async def _is_rank_page_cache_refresh_command(event: Event, state: T_State) -> bool:
    command = parse_rank_page_cache_refresh_command(event.get_plaintext())
    if command is None:
        return False

    state[RANK_PAGE_CACHE_REFRESH_COMMAND_KEY] = command
    return True


def _with_game(
    group: SeerMatcherGroup,
    handler: GameHandler,
) -> Callable[[Matcher, MessageEvent, T_State], Awaitable[None]]:
    async def bound_handler(
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        await handler(matcher, event, state, group.headless.get_game())

    return bound_handler


def install(group: SeerMatcherGroup) -> None:
    help_matcher = group.on_fullmatch(
        RANK_HELP_DETAIL_COMMANDS,
        policy=CommandPolicy.command("seer_rank_help"),
        rule=seer_feature_rule(group.features, "seer_rank") & no_reply(),
        priority=group.matcher_priority("seer_rank_help"),
    )
    help_matcher.append_handler(rank_list_query_handlers.handle_help)

    list_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_list"),
        rule=seer_feature_rule(group.features, "seer_rank")
        & Rule(_is_rank_list_command)
        & no_reply(),
        priority=group.matcher_priority("seer_rank"),
    )
    list_matcher.append_handler(
        _with_game(group, rank_list_query_handlers.handle_list)
    )

    player_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_player"),
        rule=seer_feature_rule(group.features, "seer_rank")
        & Rule(_is_rank_player_command)
        & no_reply(),
        priority=group.matcher_priority("seer_rank"),
    )
    player_matcher.append_handler(
        _with_game(group, rank_list_query_handlers.handle_player)
    )

    score_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_score"),
        rule=seer_feature_rule(group.features, "seer_rank")
        & Rule(_is_rank_score_command)
        & no_reply(),
        priority=group.matcher_priority("seer_rank"),
    )
    score_matcher.append_handler(
        _with_game(group, rank_list_query_handlers.handle_score)
    )

    cache_status_matcher = group.on_fullmatch(
        with_admin_prefix(("样本情况", "样本状态")),
        policy=CommandPolicy.command("seer_rank_cache_status"),
        rule=seer_feature_rule(group.features, "seer_rank") & no_reply(),
        permission=SUPERUSER,
        priority=group.matcher_priority("seer_rank"),
    )
    cache_status_matcher.append_handler(
        rank_list_cache_handlers.handle_cache_status
    )

    cache_refresh_matcher = group.on_fullmatch(
        with_admin_prefix(("刷新样本",)),
        policy=CommandPolicy.command("seer_rank_cache_refresh"),
        rule=seer_feature_rule(group.features, "seer_rank") & no_reply(),
        permission=SUPERUSER,
        priority=group.matcher_priority("seer_rank"),
    )
    cache_refresh_matcher.append_handler(
        _with_game(
            group,
            partial(
                rank_list_cache_handlers.handle_cache_refresh,
                priority=group.priority,
            ),
        )
    )

    cache_batch_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_cache_batch"),
        rule=seer_feature_rule(group.features, "seer_rank")
        & Rule(_is_rank_cache_batch_command)
        & no_reply(),
        permission=SUPERUSER,
        priority=group.matcher_priority("seer_rank"),
    )
    cache_batch_matcher.append_handler(
        _with_game(
            group,
            partial(
                rank_list_cache_handlers.handle_cache_batch,
                priority=group.priority,
            ),
        )
    )

    page_overview_matcher = group.on_fullmatch(
        with_admin_prefix(("榜单情况", "榜单状态")),
        policy=CommandPolicy.command("seer_rank_page_cache_status"),
        rule=seer_feature_rule(group.features, "seer_rank") & no_reply(),
        permission=SUPERUSER,
        priority=group.matcher_priority("seer_rank"),
    )
    page_overview_matcher.append_handler(
        rank_list_cache_handlers.handle_page_cache_overview
    )

    page_status_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_page_cache_status"),
        rule=seer_feature_rule(group.features, "seer_rank")
        & Rule(_is_rank_page_cache_status_command)
        & no_reply(),
        permission=SUPERUSER,
        priority=group.matcher_priority("seer_rank"),
    )
    page_status_matcher.append_handler(
        rank_list_cache_handlers.handle_page_cache_status
    )

    page_refresh_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_page_cache_refresh"),
        rule=seer_feature_rule(group.features, "seer_rank")
        & Rule(_is_rank_page_cache_refresh_command)
        & no_reply(),
        permission=SUPERUSER,
        priority=group.matcher_priority("seer_rank"),
    )
    page_refresh_matcher.append_handler(
        _with_game(
            group,
            partial(
                rank_list_cache_handlers.handle_page_cache_refresh,
                priority=group.priority,
            ),
        )
    )

    display_limit_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_display_limit"),
        rule=seer_feature_rule(group.features, "seer_rank")
        & Rule(_is_rank_display_limit_command)
        & no_reply(),
        priority=group.matcher_priority("seer_rank"),
    )
    display_limit_matcher.append_handler(
        partial(
            rank_list_display_handlers.handle_display_limit,
            features=group.features,
        )
    )
