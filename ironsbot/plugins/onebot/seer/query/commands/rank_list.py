# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.runtime.matchers import CommandPolicy, bind, bind_async
from ironsbot.runtime.message_input import message_input_context
from ironsbot.runtime.permissions import can_manage_group_event
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import explicit_command, member_target_command
from ironsbot.services.seer.rank_display import parse_rank_display_limit_command
from ironsbot.services.seer.rank_list_parsing import (
    parse_rank_cache_batch_command,
    parse_rank_list_command,
    parse_rank_page_cache_refresh_command,
    parse_rank_page_cache_status_command,
    parse_rank_player_target_command,
    parse_rank_score_command,
    with_admin_prefix,
)

from ..group import SeerMatcherGroup, seer_feature_rule
from .player_target import event_player_reference_lookup, resolve_player_target
from .rank_list_context import (
    RANK_CACHE_BATCH_COMMAND_KEY,
    RANK_DISPLAY_LIMIT_COMMAND_KEY,
    RANK_LIST_COMMAND_KEY,
    RANK_PAGE_CACHE_REFRESH_COMMAND_KEY,
    RANK_PAGE_CACHE_STATUS_COMMAND_KEY,
    RANK_PLAYER_COMMAND_KEY,
    RANK_SCORE_COMMAND_KEY,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.seer.rank_admin import RankAdminService
    from ironsbot.services.seer.rank_list_models import RankPlayerCommand
    from ironsbot.services.seer.rank_queries import RankQueryService


@dataclass(frozen=True, slots=True)
class _ResolvedRankPlayerCommand:
    command: RankPlayerCommand | None
    error: str | None = None


def _is_rank_list_command(
    service: RankQueryService,
    event: Event,
    state: T_State,
) -> bool:
    command = parse_rank_list_command(
        event.get_plaintext(),
        default_limit=service.default_limit(
            message_input_context(event).message.conversation
        ),
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


def _is_rank_player_command(
    group: SeerMatcherGroup,
    event: MessageEvent,
    state: T_State,
) -> bool:
    requested = parse_rank_player_target_command(event.get_plaintext())
    if requested is None:
        return False
    context = message_input_context(event)
    if requested.player_reference is None and not context.has_member_mentions:
        return False
    target = resolve_player_target(
        event,
        player_reference=requested.player_reference,
        reference_lookup=event_player_reference_lookup(group.player_accounts, event),
        binding_for_user=group.resources.player.default_player_id,
        allow_default_binding=False,
    )
    if target.player_id is None and target.error is None:
        return False
    from ironsbot.services.seer.rank_list_models import RankPlayerCommand

    state[RANK_PLAYER_COMMAND_KEY] = _ResolvedRankPlayerCommand(
        command=(
            RankPlayerCommand(requested.rank_key, target.player_id)
            if target.player_id is not None
            else None
        ),
        error=target.error,
    )
    return True


async def _handle_list(
    service: RankQueryService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    message = await service.list(
        state[RANK_LIST_COMMAND_KEY],
        actor=message_input_context(event).message.actor,
        conversation=message_input_context(event).message.conversation,
    )
    await finish_event_reply(matcher, event, message)


async def _handle_score(
    service: RankQueryService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    message = await service.score(
        state[RANK_SCORE_COMMAND_KEY],
        conversation=message_input_context(event).message.conversation,
        actor=message_input_context(event).message.actor,
    )
    await finish_event_reply(matcher, event, message)


async def _handle_player(
    service: RankQueryService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    resolved = state[RANK_PLAYER_COMMAND_KEY]
    if not isinstance(resolved, _ResolvedRankPlayerCommand):
        return
    if resolved.error is not None:
        await finish_event_reply(matcher, event, resolved.error)
        return
    if resolved.command is None:
        return
    message = await service.player(
        resolved.command,
        actor=message_input_context(event).message.actor,
        conversation=message_input_context(event).message.conversation,
    )
    await finish_event_reply(matcher, event, message)


async def _progress(
    matcher: Matcher,
    event: MessageEvent,
    message: str,
) -> None:
    await send_event_reply(matcher, event, message)


async def _handle_cache_batch(
    service: RankAdminService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    message = await service.cache_batch(
        state[RANK_CACHE_BATCH_COMMAND_KEY],
        actor=message_input_context(event).message.actor,
        progress=partial(_progress, matcher, event),
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
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    message = await service.page_refresh(
        state[RANK_PAGE_CACHE_REFRESH_COMMAND_KEY],
        actor=message_input_context(event).message.actor,
        progress=partial(_progress, matcher, event),
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
        service.cache_status(message_input_context(event).message.conversation),
    )


async def _handle_cache_refresh(
    service: RankAdminService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    message = await service.cache_refresh(
        actor=message_input_context(event).message.actor,
        progress=partial(_progress, matcher, event),
    )
    await finish_event_reply(matcher, event, message)


async def _handle_display_limit(
    service: RankQueryService,
    features: FeatureService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    message = service.set_display_limit(
        conversation=message_input_context(event).message.conversation,
        actor=message_input_context(event).message.actor,
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
    feature_rule = seer_feature_rule(group.features, "seer_rank") & explicit_command()
    player_feature_rule = (
        seer_feature_rule(group.features, "seer_rank") & member_target_command()
    )
    priority = group.matcher_priority("seer_rank")

    list_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_list",
            help_ids=(
                "rank.global_collection",
                "rank.global_peak",
                "rank.sample_collection",
                "rank.sample_peak",
            ),
        ),
        rule=feature_rule & Rule(bind(_is_rank_list_command, query)),
        priority=priority,
    )
    list_matcher.append_handler(bind_async(_handle_list, query))

    player_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_player",
            help_ids=("rank.global_collection", "rank.global_peak"),
        ),
        rule=player_feature_rule & Rule(bind(_is_rank_player_command, group)),
        priority=priority,
    )
    player_matcher.append_handler(bind_async(_handle_player, query))

    score_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_score",
            help_ids=("rank.global_collection", "rank.global_peak"),
        ),
        rule=feature_rule
        & Rule(
            bind(
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
        policy=CommandPolicy.command(
            "seer_rank_cache_status",
            help_ids=("rank.sample_status",),
        ),
        rule=feature_rule,
        permission=SUPERUSER,
        priority=priority,
    )
    cache_status.append_handler(bind_async(_handle_cache_status, admin))

    cache_refresh = group.on_fullmatch(
        with_admin_prefix(("刷新样本",)),
        policy=CommandPolicy.command(
            "seer_rank_cache_refresh",
            help_ids=("rank.sample_refresh",),
        ),
        rule=feature_rule,
        permission=SUPERUSER,
        priority=priority,
    )
    cache_refresh.append_handler(
        bind_async(
            _handle_cache_refresh,
            admin,
        )
    )

    cache_batch = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_cache_batch",
            help_ids=("rank.page_batch",),
        ),
        rule=feature_rule
        & Rule(
            bind(
                _store_command,
                parse_rank_cache_batch_command,
                RANK_CACHE_BATCH_COMMAND_KEY,
            )
        ),
        permission=SUPERUSER,
        priority=priority,
    )
    cache_batch.append_handler(bind_async(_handle_cache_batch, admin))

    page_overview = group.on_fullmatch(
        with_admin_prefix(("榜单情况", "榜单状态")),
        policy=CommandPolicy.command(
            "seer_rank_page_cache_status",
            help_ids=("rank.page_status",),
        ),
        rule=feature_rule,
        permission=SUPERUSER,
        priority=priority,
    )
    page_overview.append_handler(bind_async(_handle_page_overview, admin))

    page_status = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_page_cache_status",
            help_ids=("rank.page_status",),
        ),
        rule=feature_rule
        & Rule(
            bind(
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
        policy=CommandPolicy.command(
            "seer_rank_page_cache_refresh",
            help_ids=("rank.page_refresh",),
        ),
        rule=feature_rule
        & Rule(
            bind(
                _store_command,
                parse_rank_page_cache_refresh_command,
                RANK_PAGE_CACHE_REFRESH_COMMAND_KEY,
            )
        ),
        permission=SUPERUSER,
        priority=priority,
    )
    page_refresh.append_handler(bind_async(_handle_page_refresh, admin))

    display_limit = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_display_limit",
            help_ids=("rank.display_limit",),
        ),
        rule=feature_rule
        & Rule(
            bind(
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
