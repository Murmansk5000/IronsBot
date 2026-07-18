# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule
from nonebot.typing import T_State

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

from ..group import SeerMatcherGroup, seer_feature_priority, seer_feature_rule
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


async def handle_rank_help(matcher: Matcher, event: MessageEvent) -> None:
    await rank_list_query_handlers.handle_help(matcher, event)


async def handle_rank_list(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await rank_list_query_handlers.handle_list(matcher, event, state)


async def handle_rank_score(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await rank_list_query_handlers.handle_score(matcher, event, state)


async def handle_rank_player(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await rank_list_query_handlers.handle_player(matcher, event, state)


async def handle_rank_cache_batch(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await rank_list_cache_handlers.handle_cache_batch(matcher, event, state)


async def handle_rank_page_cache_status(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await rank_list_cache_handlers.handle_page_cache_status(matcher, event, state)


async def handle_rank_page_cache_overview(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await rank_list_cache_handlers.handle_page_cache_overview(matcher, event)


async def handle_rank_page_cache_refresh(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await rank_list_cache_handlers.handle_page_cache_refresh(matcher, event, state)


async def handle_rank_cache_status(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await rank_list_cache_handlers.handle_cache_status(matcher, event)


async def handle_rank_cache_refresh(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await rank_list_cache_handlers.handle_cache_refresh(matcher, event, state)


async def handle_rank_display_limit(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await rank_list_display_handlers.handle_display_limit(matcher, event, state)


def install(group: SeerMatcherGroup) -> None:
    help_matcher = group.on_fullmatch(
        RANK_HELP_DETAIL_COMMANDS,
        policy=CommandPolicy.command("seer_rank_help"),
        rule=seer_feature_rule("seer_rank") & no_reply(),
        priority=seer_feature_priority("seer_rank_help"),
    )
    help_matcher.append_handler(handle_rank_help)

    list_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_list"),
        rule=seer_feature_rule("seer_rank")
        & Rule(_is_rank_list_command)
        & no_reply(),
        priority=seer_feature_priority("seer_rank"),
    )
    list_matcher.append_handler(handle_rank_list)

    player_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_player"),
        rule=seer_feature_rule("seer_rank")
        & Rule(_is_rank_player_command)
        & no_reply(),
        priority=seer_feature_priority("seer_rank"),
    )
    player_matcher.append_handler(handle_rank_player)

    score_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_score"),
        rule=seer_feature_rule("seer_rank")
        & Rule(_is_rank_score_command)
        & no_reply(),
        priority=seer_feature_priority("seer_rank"),
    )
    score_matcher.append_handler(handle_rank_score)

    cache_status_matcher = group.on_fullmatch(
        with_admin_prefix(("样本情况", "样本状态")),
        policy=CommandPolicy.command("seer_rank_cache_status"),
        rule=seer_feature_rule("seer_rank") & no_reply(),
        permission=SUPERUSER,
        priority=seer_feature_priority("seer_rank"),
    )
    cache_status_matcher.append_handler(handle_rank_cache_status)

    cache_refresh_matcher = group.on_fullmatch(
        with_admin_prefix(("刷新样本",)),
        policy=CommandPolicy.command("seer_rank_cache_refresh"),
        rule=seer_feature_rule("seer_rank") & no_reply(),
        permission=SUPERUSER,
        priority=seer_feature_priority("seer_rank"),
    )
    cache_refresh_matcher.append_handler(handle_rank_cache_refresh)

    cache_batch_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_cache_batch"),
        rule=seer_feature_rule("seer_rank")
        & Rule(_is_rank_cache_batch_command)
        & no_reply(),
        permission=SUPERUSER,
        priority=seer_feature_priority("seer_rank"),
    )
    cache_batch_matcher.append_handler(handle_rank_cache_batch)

    page_overview_matcher = group.on_fullmatch(
        with_admin_prefix(("榜单情况", "榜单状态")),
        policy=CommandPolicy.command("seer_rank_page_cache_status"),
        rule=seer_feature_rule("seer_rank") & no_reply(),
        permission=SUPERUSER,
        priority=seer_feature_priority("seer_rank"),
    )
    page_overview_matcher.append_handler(handle_rank_page_cache_overview)

    page_status_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_page_cache_status"),
        rule=seer_feature_rule("seer_rank")
        & Rule(_is_rank_page_cache_status_command)
        & no_reply(),
        permission=SUPERUSER,
        priority=seer_feature_priority("seer_rank"),
    )
    page_status_matcher.append_handler(handle_rank_page_cache_status)

    page_refresh_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_page_cache_refresh"),
        rule=seer_feature_rule("seer_rank")
        & Rule(_is_rank_page_cache_refresh_command)
        & no_reply(),
        permission=SUPERUSER,
        priority=seer_feature_priority("seer_rank"),
    )
    page_refresh_matcher.append_handler(handle_rank_page_cache_refresh)

    display_limit_matcher = group.on_message(
        policy=CommandPolicy.command("seer_rank_display_limit"),
        rule=seer_feature_rule("seer_rank")
        & Rule(_is_rank_display_limit_command)
        & no_reply(),
        priority=seer_feature_priority("seer_rank"),
    )
    display_limit_matcher.append_handler(handle_rank_display_limit)


__all__ = ["install"]
