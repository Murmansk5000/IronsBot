# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, field
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
from ironsbot.runtime.onebot_context import event_group_id
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import BOT_COMMAND_ARG_KEY, no_reply
from ironsbot.services.seer.ids import (
    PLAYER_ID_ERROR_MESSAGE,
    PLAYER_ID_MAX,
    PLAYER_ID_MIN,
    is_valid_player_id,
)
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_query import extract_player_query_arg
from ironsbot.services.seer.player_service import (
    PendingPlayerQuery,
    PlayerQueryResult,
)

from ..group import SeerMatcherGroup, seer_feature_rule
from ._args import parse_numeric_id
from .player_context import (
    PLAYER_BINDING_NAMESPACE,
    PLAYER_BINDING_PENDING_KEY,
    PLAYER_ID_KEY,
    PLAYER_QUERY_IS_EXPLICIT_KEY,
    PLAYER_UNBOUND_ENTRY_NAMESPACE,
)
from .player_detail_conversation import send_player_info_with_detail_prompt

if TYPE_CHECKING:
    from ironsbot.core.features import FeatureService
    from ironsbot.services.seer.player_service import PlayerService

@dataclass(frozen=True, slots=True)
class PlayerCommandDependencies:
    player: PlayerService
    features: FeatureService
    detail_extensions: PlayerDetailExtensionRegistry = field(
        default_factory=PlayerDetailExtensionRegistry
    )


def _parse_pending_binding_choice(text: str, player_id: int) -> bool | None:
    _ = player_id
    return parse_confirmation(text)


def _unbound_player_entry_prompt(error: str = "") -> str:
    prompt = (
        "尚未设置默认米米号，请直接发送数字（例如 123456）。\n"
        "查询成功后可按提示选择设为默认。"
    )
    return f"{error}\n\n{prompt}" if error else prompt


def _is_unbound_player_id_reply(event: MessageEvent) -> bool:
    return event.get_plaintext().strip().isdigit()


async def prompt_for_unbound_player_id(
    dependencies: PlayerCommandDependencies,
    matcher: Matcher,
    event: MessageEvent,
    *,
    error: str = "",
) -> None:
    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=PLAYER_UNBOUND_ENTRY_NAMESPACE,
        handlers=[bind_async(handle_unbound_player_id_entry, dependencies)],
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


async def validate_player_id(
    dependencies: PlayerCommandDependencies,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    if state.get(PLAYER_QUERY_IS_EXPLICIT_KEY, True):
        player_id = await parse_numeric_id(
            matcher,
            state,
            min_value=PLAYER_ID_MIN,
            max_value=PLAYER_ID_MAX,
            error_message=PLAYER_ID_ERROR_MESSAGE,
        )
    else:
        player_id = dependencies.player.default_player_id(event.user_id)
        if player_id is None:
            await prompt_for_unbound_player_id(
                dependencies,
                matcher,
                event,
            )
            return
    state[PLAYER_ID_KEY] = player_id


async def handle_player(
    dependencies: PlayerCommandDependencies,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    explicit = bool(state.get(PLAYER_QUERY_IS_EXPLICIT_KEY, True))
    result = await dependencies.player.query(
        int(state[PLAYER_ID_KEY]),
        qq_user_id=event.user_id,
        explicit=explicit,
        group_id=event_group_id(event),
    )
    await _handle_player_query_result(
        dependencies,
        matcher,
        event,
        state,
        result,
    )


async def handle_unbound_player_id_entry(
    dependencies: PlayerCommandDependencies,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    raw_player_id = event.get_plaintext().strip()
    player_id = int(raw_player_id)
    if not is_valid_player_id(player_id):
        await prompt_for_unbound_player_id(
            dependencies,
            matcher,
            event,
            error=PLAYER_ID_ERROR_MESSAGE,
        )
        return

    result = await dependencies.player.query(
        player_id,
        qq_user_id=event.user_id,
        explicit=True,
        group_id=event_group_id(event),
    )
    if result.message:
        await prompt_for_unbound_player_id(
            dependencies,
            matcher,
            event,
            error=result.message,
        )
        return
    await _handle_player_query_result(
        dependencies,
        matcher,
        event,
        state,
        result,
    )


async def _handle_player_query_result(
    dependencies: PlayerCommandDependencies,
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
            handlers=[bind_async(handle_player_binding_choice, dependencies)],
            reply_check=lambda reply: (
                _parse_pending_binding_choice(
                    reply.get_plaintext(),
                    pending.player_id,
                )
                is not None
            ),
            prompt=dependencies.player.binding_offer(pending),
        )
    await _send_pending_player_query(
        dependencies,
        matcher,
        event,
        state,
        pending,
    )


async def handle_player_binding_choice(
    dependencies: PlayerCommandDependencies,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    pending = state.get(PLAYER_BINDING_PENDING_KEY)
    if not isinstance(pending, PendingPlayerQuery):
        return
    choice = _parse_pending_binding_choice(
        event.get_plaintext(),
        pending.player_id,
    )
    if choice is None:
        return
    dependencies.player.save_binding_choice(
        event.user_id,
        pending,
        accepted=choice,
    )
    await _send_pending_player_query(
        dependencies,
        matcher,
        event,
        state,
        pending,
    )


async def _send_pending_player_query(
    dependencies: PlayerCommandDependencies,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    pending: PendingPlayerQuery,
) -> None:
    plan = pending.section_plan

    def after_initial_reply_sent() -> None:
        dependencies.player.record_returned_query(event.user_id, pending)
        dependencies.player.start_background_refresh(
            pending,
            group_id=event_group_id(event),
        )

    await send_player_info_with_detail_prompt(
        dependencies.player,
        dependencies.features,
        dependencies.detail_extensions,
        matcher,
        event,
        state,
        player_id=pending.player_id,
        player_message=pending.player_message,
        has_collection=plan.has_collection,
        has_peak=plan.needs_peak_section,
        has_autocard=plan.has_autocard_rank,
        on_sent=after_initial_reply_sent,
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
    dependencies = PlayerCommandDependencies(
        service,
        group.features,
        group.resources.player_detail_extensions,
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
    query_matcher.append_handler(
        bind_async(validate_player_id, dependencies)
    )
    query_matcher.append_handler(bind_async(handle_player, dependencies))
