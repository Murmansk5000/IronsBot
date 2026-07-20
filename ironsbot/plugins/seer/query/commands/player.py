# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (
    MessageEvent,  # noqa: TC002 - NoneBot resolves it at runtime
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.core.commands import parse_confirmation
from ironsbot.runtime.conversations import enter_event_reply_conversation
from ironsbot.runtime.matchers import CommandPolicy, bind_async
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import BOT_COMMAND_ARG_KEY, no_reply
from ironsbot.services.seer.player_binding import parse_player_binding_target
from ironsbot.services.seer.player_query import extract_player_query_arg
from ironsbot.services.seer.player_service import (
    PendingPlayerQuery,
    PlayerQueryResult,
)

from ..group import SeerMatcherGroup, seer_feature_rule
from ._args import parse_numeric_id
from .player_context import (
    PLAYER_BINDING_COMMAND_ID_KEY,
    PLAYER_BINDING_NAMESPACE,
    PLAYER_BINDING_PENDING_KEY,
    PLAYER_ID_KEY,
    PLAYER_QUERY_IS_EXPLICIT_KEY,
    PLAYER_UNBOUND_ENTRY_NAMESPACE,
)
from .player_detail_conversation import send_player_info_with_detail_prompt

if TYPE_CHECKING:
    from ironsbot.services.seer.player_service import PlayerService

_MAX_PLAYER_ID = 2_000_000_000


def _unbound_player_entry_prompt(error: str = "") -> str:
    prompt = (
        "尚未设置默认米米号。请直接发送米米号数字（例如 123456）查询，"
        "也可发送“米米号123456”查询或“绑定米米号123456”直接绑定。\n"
        "首次成功查询后，机器人会询问是否设为默认米米号。"
    )
    return f"{error}\n\n{prompt}" if error else prompt


def _is_unbound_player_id_reply(event: MessageEvent) -> bool:
    return event.get_plaintext().strip().isdigit()


async def prompt_for_unbound_player_id(
    service: PlayerService,
    matcher: Matcher,
    event: MessageEvent,
    *,
    error: str = "",
) -> None:
    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=PLAYER_UNBOUND_ENTRY_NAMESPACE,
        handlers=[bind_async(handle_unbound_player_id_entry, service)],
        reply_check=_is_unbound_player_id_reply,
        prompt=_unbound_player_entry_prompt(error),
    )


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
            await prompt_for_unbound_player_id(
                service,
                matcher,
                event,
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
    await _handle_player_query_result(
        service,
        matcher,
        event,
        state,
        result,
    )


async def handle_unbound_player_id_entry(
    service: PlayerService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    raw_player_id = event.get_plaintext().strip()
    player_id = int(raw_player_id)
    if not 1 <= player_id <= _MAX_PLAYER_ID:
        await prompt_for_unbound_player_id(
            service,
            matcher,
            event,
            error="❌ 米米号无效，请输入纯数字米米号。",
        )
        return

    result = await service.query(
        player_id,
        qq_user_id=event.user_id,
        explicit=True,
    )
    if result.message:
        await prompt_for_unbound_player_id(
            service,
            matcher,
            event,
            error=result.message,
        )
        return
    await _handle_player_query_result(
        service,
        matcher,
        event,
        state,
        result,
    )


async def _handle_player_query_result(
    service: PlayerService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    result: PlayerQueryResult,
) -> None:
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
            handlers=[bind_async(handle_player_binding_choice, service)],
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
        bind_async(handle_player_binding_command, service)
    )

    unbind_matcher = group.on_fullmatch(
        ("解绑米米号",),
        policy=CommandPolicy.command("seer_player_binding"),
        rule=seer_feature_rule(group.features, "seer_player") & no_reply(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    unbind_matcher.append_handler(bind_async(handle_player_unbind, service))

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
    query_matcher.append_handler(bind_async(validate_player_id, service))
    query_matcher.append_handler(bind_async(handle_player, service))
