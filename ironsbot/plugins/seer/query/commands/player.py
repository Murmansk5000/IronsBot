# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.rule import Rule

from ironsbot.core.commands import parse_confirmation
from ironsbot.runtime.conversations import enter_event_reply_conversation
from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import BOT_COMMAND_ARG_KEY, no_reply
from ironsbot.services.seer.player_binding import parse_player_binding_target
from ironsbot.services.seer.player_query import extract_player_query_arg
from ironsbot.services.seer.player_service import PendingPlayerQuery

from ..group import SeerMatcherGroup, seer_feature_rule
from ._args import parse_numeric_id
from .player_context import (
    PLAYER_BINDING_COMMAND_ID_KEY,
    PLAYER_BINDING_NAMESPACE,
    PLAYER_BINDING_PENDING_KEY,
    PLAYER_ID_KEY,
    PLAYER_QUERY_IS_EXPLICIT_KEY,
)
from .player_detail_conversation import send_player_info_with_detail_prompt

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

    from ironsbot.services.seer.player_service import PlayerService

_MAX_PLAYER_ID = 2_000_000_000


async def _is_player_id_query(event: Event, state: T_State) -> bool:
    arg = extract_player_query_arg(event.get_plaintext())
    if arg is None:
        return False
    if not arg:
        state[PLAYER_QUERY_IS_EXPLICIT_KEY] = False
        return True
    if not arg.isdigit():
        return False
    state[BOT_COMMAND_ARG_KEY] = arg
    state[PLAYER_QUERY_IS_EXPLICIT_KEY] = True
    return True


async def _is_invalid_player_text_query(event: Event) -> bool:
    arg = extract_player_query_arg(event.get_plaintext())
    return arg is not None and bool(arg) and not arg.isdigit()


async def _is_binding_command(event: Event, state: T_State) -> bool:
    player_id = parse_player_binding_target(event.get_plaintext())
    if player_id is None:
        return False
    state[PLAYER_BINDING_COMMAND_ID_KEY] = player_id
    return True


async def validate_player_id(
    service: PlayerService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    if state.get(PLAYER_QUERY_IS_EXPLICIT_KEY, True):
        player_id = await parse_numeric_id(
            matcher,
            state,
            min_value=1,
            max_value=_MAX_PLAYER_ID,
            error_message="❌ 米米号无效，请输入纯数字米米号。",
        )
    else:
        player_id = service.default_player_id(event.user_id)
        if player_id is None:
            await finish_event_reply(
                matcher,
                event,
                "尚未设置默认米米号，请先发送“米米号+数字”查询。\n"
                "首次成功查询后可以选择是否设为默认米米号。",
            )
            return
    state[PLAYER_ID_KEY] = player_id


async def handle_player(
    service: PlayerService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    explicit = bool(state.get(PLAYER_QUERY_IS_EXPLICIT_KEY, True))
    result = await service.query(
        int(state[PLAYER_ID_KEY]),
        qq_user_id=event.user_id,
        explicit=explicit,
    )
    if result.message:
        await finish_event_reply(matcher, event, result.message)
        return
    pending = result.pending
    if pending is None:
        return
    if result.offer_binding:
        state[PLAYER_BINDING_PENDING_KEY] = pending
        await enter_event_reply_conversation(
            matcher,
            event,
            namespace=PLAYER_BINDING_NAMESPACE,
            handlers=[partial(handle_player_binding_choice, service)],
            reply_check=lambda reply: (
                parse_confirmation(reply.get_plaintext()) is not None
            ),
            prompt=service.binding_offer(pending),
        )
    await _send_pending_player_query(
        service,
        matcher,
        event,
        state,
        pending,
    )


async def handle_player_binding_choice(
    service: PlayerService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    pending = state.get(PLAYER_BINDING_PENDING_KEY)
    if not isinstance(pending, PendingPlayerQuery):
        return
    choice = parse_confirmation(event.get_plaintext())
    if choice is None:
        return
    service.save_binding_choice(
        event.user_id,
        pending,
        accepted=choice,
    )
    await _send_pending_player_query(
        service,
        matcher,
        event,
        state,
        pending,
    )


async def _send_pending_player_query(
    service: PlayerService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    pending: PendingPlayerQuery,
) -> None:
    plan = pending.section_plan
    await send_player_info_with_detail_prompt(
        service.spawn_task,
        matcher,
        event,
        state,
        player_message=pending.player_message,
        error_formatter=service.format_error,
        detail_task=service.create_detail_task(pending),
        has_collection=plan.has_collection,
        has_peak=plan.needs_peak_section,
        has_autocard=plan.has_autocard_rank,
    )


async def handle_player_binding_command(
    service: PlayerService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    player_id = int(state[PLAYER_BINDING_COMMAND_ID_KEY])
    if not 1 <= player_id <= _MAX_PLAYER_ID:
        await finish_event_reply(
            matcher,
            event,
            "❌ 米米号无效，请输入纯数字米米号。",
        )
        return
    result = await service.bind_player(event.user_id, player_id)
    if result.message:
        await finish_event_reply(matcher, event, result.message)
        return
    if result.pending is not None:
        await _send_pending_player_query(
            service,
            matcher,
            event,
            state,
            result.pending,
        )


async def handle_player_unbind(
    service: PlayerService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(
        matcher,
        event,
        service.unbind(event.user_id),
    )


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.player
    binding_matcher = group.on_message(
        policy=CommandPolicy.command("seer_player_binding"),
        rule=seer_feature_rule(group.features, "seer_player")
        & Rule(_is_binding_command)
        & no_reply(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    binding_matcher.append_handler(
        partial(handle_player_binding_command, service)
    )

    unbind_matcher = group.on_fullmatch(
        ("解绑米米号",),
        policy=CommandPolicy.command("seer_player_binding"),
        rule=seer_feature_rule(group.features, "seer_player") & no_reply(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    unbind_matcher.append_handler(partial(handle_player_unbind, service))

    group.on_message(
        policy=CommandPolicy.exempt("silent invalid player query blocker"),
        rule=seer_feature_rule(group.features, "seer_player")
        & Rule(_is_invalid_player_text_query)
        & no_reply(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )

    query_matcher = group.on_message(
        policy=CommandPolicy.command("seer_player"),
        rule=seer_feature_rule(group.features, "seer_player")
        & Rule(_is_player_id_query)
        & no_reply(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    query_matcher.append_handler(partial(validate_player_id, service))
    query_matcher.append_handler(partial(handle_player, service))
