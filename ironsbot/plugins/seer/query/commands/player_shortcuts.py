# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.core.request_coordination import (
    RequestDecision,
    request_response_scope,
)
from ironsbot.runtime.feature_policy import event_is_feature_allowed
from ironsbot.runtime.matchers import CommandPolicy, bind_async
from ironsbot.runtime.onebot_context import event_group_id
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import member_target_command
from ironsbot.runtime.semantic_requests import (
    SemanticRequest,
    SemanticRequestSource,
)
from ironsbot.services.seer.ids import is_valid_player_id
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message
from ironsbot.services.seer.player_shortcuts import (
    PlayerShortcutCommand,
    execute_player_shortcut,
    parse_player_shortcut_command,
    player_request_admission_message,
    player_shortcut_semantic_request,
)

from ..group import SeerMatcherGroup, seer_feature_rule
from .player import PlayerCommandDependencies
from .player_target import (
    PlayerTargetResolution,
    allows_private_player_aliases,
    default_player_id_for,
    resolve_event_player_target,
)
from .player_target_selection import enter_player_target_selection

if TYPE_CHECKING:
    from ironsbot.services.seer.player_detail_extensions import (
        PlayerDetailExtensionAction,
    )
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.query_work import QueryWorkMeter, query_work_scope

_SHORTCUT_COMMAND_KEY = "_player_shortcut_command"
_EXTENSION_SHORTCUT_COMMAND_KEY = "_player_extension_shortcut_command"
_SHORTCUT_TARGET_KEY = "_player_shortcut_target"
_EXTENSION_SHORTCUT_TARGET_KEY = "_player_extension_shortcut_target"


@dataclass(frozen=True, slots=True)
class PlayerExtensionShortcutCommand:
    """An extension action plus its normalized player target reference."""

    action: PlayerDetailExtensionAction
    player_id: int | None
    player_reference: str | None = None


def _build_shortcut_reply_message(reply: QueryReply) -> str | Message:
    if reply.image is None:
        return f"{reply.leading_text}{reply.text}"

    message = Message()
    if reply.leading_text:
        message += MessageSegment.text(reply.leading_text)
    message += MessageSegment.image(reply.image)
    if reply.text:
        message += MessageSegment.text(reply.text)
    return message


async def _is_player_shortcut(
    event: Event,
    state: T_State,
    *,
    dependencies: PlayerCommandDependencies,
) -> bool:
    command = parse_player_shortcut_command(event.get_plaintext())
    if command is None:
        return False
    target = resolve_event_player_target(
        dependencies.player_accounts,
        event,
        command.player_reference
        if command.player_reference is not None
        else (str(command.player_id) if command.player_id is not None else None),
        binding_for_user=lambda user_id: default_player_id_for(
            dependencies.player, user_id
        ),
        allow_private=allows_private_player_aliases(
            dependencies.features, int(event.get_user_id())
        ),
        allow_partial_reference=True,
    )
    if not target.recognized:
        return False
    if command.player_reference is not None and target.player_id is not None:
        command = PlayerShortcutCommand(kind=command.kind, player_id=target.player_id)
    state[_SHORTCUT_COMMAND_KEY] = command
    state[_SHORTCUT_TARGET_KEY] = target
    return True


async def _is_player_extension_shortcut(
    event: Event,
    state: T_State,
    *,
    dependencies: PlayerCommandDependencies,
) -> bool:
    resolved = dependencies.detail_extensions.resolve_direct_command(
        event.get_plaintext()
    )
    if resolved is None:
        return False
    action, player_reference = resolved
    if not event_is_feature_allowed(dependencies.features, event, action.feature):
        return False
    target = resolve_event_player_target(
        dependencies.player_accounts,
        event,
        player_reference or None,
        binding_for_user=lambda user_id: default_player_id_for(
            dependencies.player, user_id
        ),
        allow_private=allows_private_player_aliases(
            dependencies.features, int(event.get_user_id())
        ),
        allow_partial_reference=True,
    )
    if not target.recognized:
        return False
    state[_EXTENSION_SHORTCUT_COMMAND_KEY] = PlayerExtensionShortcutCommand(
        action=action,
        player_id=target.player_id,
        player_reference=(player_reference or None)
        if target.player_id is None
        else None,
    )
    state[_EXTENSION_SHORTCUT_TARGET_KEY] = target
    return True


async def handle_player_shortcut(
    dependencies: PlayerCommandDependencies,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    service = dependencies.player
    command: PlayerShortcutCommand = state[_SHORTCUT_COMMAND_KEY]
    target = state.get(_SHORTCUT_TARGET_KEY)
    if not isinstance(target, PlayerTargetResolution):
        target = resolve_event_player_target(
            dependencies.player_accounts,
            event,
            command.player_reference
            if command.player_reference is not None
            else (str(command.player_id) if command.player_id is not None else None),
            binding_for_user=lambda user_id: default_player_id_for(service, user_id),
            allow_private=allows_private_player_aliases(
                dependencies.features, event.user_id
            ),
            allow_partial_reference=True,
        )
    if target.error is not None:
        await finish_event_reply(matcher, event, target.error)
        return
    if target.choices:
        async def select_player_target(
            player_id: int,
            selection_matcher: Matcher,
            selection_event: MessageEvent,
        ) -> None:
            selection_state = selection_matcher.state
            selection_state[_SHORTCUT_COMMAND_KEY] = PlayerShortcutCommand(
                kind=command.kind,
                player_id=player_id,
            )
            selection_state[_SHORTCUT_TARGET_KEY] = PlayerTargetResolution(
                player_id,
                offer_binding=True,
            )
            await handle_player_shortcut(
                dependencies,
                selection_matcher,
                selection_event,
                selection_state,
            )

        await enter_player_target_selection(
            matcher,
            event,
            state,
            target,
            select_player_target,
        )
        return
    command = PlayerShortcutCommand(kind=command.kind, player_id=target.player_id)

    async def send_status(message: str) -> None:
        await send_event_reply(matcher, event, message)

    reply = await execute_player_shortcut(
        service,
        command,
        event.user_id,
        group_id=event_group_id(event),
        send_status=send_status,
    )
    await _finish_shortcut_reply(
        service,
        command,
        matcher,
        event,
        reply,
    )


async def _finish_shortcut_reply(
    service: PlayerService,
    command: PlayerShortcutCommand,
    matcher: Matcher,
    event: MessageEvent,
    reply: QueryReply,
) -> None:
    try:
        await finish_event_reply(
            matcher,
            event,
            _build_shortcut_reply_message(reply),
        )
    except FinishedException:
        _record_shortcut_delivery(service, event.user_id, command, reply)
        raise
    else:
        _record_shortcut_delivery(service, event.user_id, command, reply)


def _record_shortcut_delivery(
    service: PlayerService,
    user_id: int,
    command: PlayerShortcutCommand,
    reply: QueryReply,
) -> None:
    record = getattr(service, "record_returned_shortcut", None)
    if callable(record):
        record(user_id, command, reply)


async def _enter_extension_target_selection(  # noqa: PLR0913
    dependencies: PlayerCommandDependencies,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    target: PlayerTargetResolution,
    command: PlayerExtensionShortcutCommand,
) -> None:
    async def select_player_target(
        player_id: int,
        selection_matcher: Matcher,
        selection_event: MessageEvent,
    ) -> None:
        selection_state = selection_matcher.state
        selection_state[_EXTENSION_SHORTCUT_COMMAND_KEY] = (
            PlayerExtensionShortcutCommand(
                action=command.action,
                player_id=player_id,
            )
        )
        selection_state[_EXTENSION_SHORTCUT_TARGET_KEY] = PlayerTargetResolution(
            player_id,
            offer_binding=True,
        )
        await handle_player_extension_shortcut(
            dependencies,
            selection_matcher,
            selection_event,
            selection_state,
        )

    await enter_player_target_selection(
        matcher,
        event,
        state,
        target,
        select_player_target,
    )


async def handle_player_extension_shortcut(
    dependencies: PlayerCommandDependencies,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    command = state.get(_EXTENSION_SHORTCUT_COMMAND_KEY)
    if not isinstance(command, PlayerExtensionShortcutCommand):
        return
    target = state.get(_EXTENSION_SHORTCUT_TARGET_KEY)
    if not isinstance(target, PlayerTargetResolution):
        target = resolve_event_player_target(
            dependencies.player_accounts,
            event,
            command.player_reference
            if command.player_reference is not None
            else (str(command.player_id) if command.player_id is not None else None),
            binding_for_user=lambda user_id: default_player_id_for(
                dependencies.player, user_id
            ),
            allow_private=allows_private_player_aliases(
                dependencies.features, event.user_id
            ),
            allow_partial_reference=True,
        )
    if target.error is not None:
        await finish_event_reply(matcher, event, target.error)
        return
    if target.choices:
        await _enter_extension_target_selection(
            dependencies,
            matcher,
            event,
            state,
            target,
            command,
        )
        return
    if target.player_id is None:
        await finish_event_reply(matcher, event, unbound_player_shortcut_message())
        return

    async def send_status(decision: RequestDecision) -> None:
        await send_event_reply(
            matcher,
            event,
            player_request_admission_message(
                decision.label,
                queued=decision.queued,
            ),
        )

    meter = QueryWorkMeter("foreground")
    with (
        request_response_scope(
            command.action.action.label,
            send_status,
        ),
        query_work_scope(meter),
    ):
        reply = await command.action.query(
            target.player_id,
            event.user_id,
            event_group_id(event),
        )
    if reply.complete and (reply.text or reply.image is not None):
        meter.succeeded(command.action.work_unit)
    reply = replace(reply, query_work=meter.result())
    try:
        await finish_event_reply(matcher, event, _build_shortcut_reply_message(reply))
    except FinishedException:
        dependencies.player.record_returned_detail_reply(
            qq_user_id=event.user_id,
            player_id=target.player_id,
            action_key=command.action.action.id,
            reply=reply,
        )
        raise
    else:
        dependencies.player.record_returned_detail_reply(
            qq_user_id=event.user_id,
            player_id=target.player_id,
            action_key=command.action.action.id,
            reply=reply,
        )


def _shortcut_command_id(
    _event: Event,
    state: T_State,
) -> str:
    command = state.get(_SHORTCUT_COMMAND_KEY)
    kind = str(getattr(command, "kind", "")).strip()
    return f"seer_player_{kind}" if kind else "seer_player"


def _shortcut_semantic_request(
    _service: PlayerService,
    _event: MessageEvent,
    state: T_State,
) -> SemanticRequest | None:
    command = state.get(_SHORTCUT_COMMAND_KEY)
    target = state.get(_SHORTCUT_TARGET_KEY)
    player_id = (
        target.player_id
        if isinstance(target, PlayerTargetResolution)
        else default_player_id_for(_service, _event.user_id)
    )
    kind = getattr(command, "kind", None)
    if not isinstance(player_id, int) or not is_valid_player_id(player_id):
        return None
    if kind not in {"collection", "peak", "autocard"}:
        return None
    return player_shortcut_semantic_request(
        kind=kind,
        player_id=player_id,
        source=SemanticRequestSource.DIRECT,
    )


def _extension_shortcut_command_id(
    _event: Event,
    state: T_State,
) -> str:
    command = state.get(_EXTENSION_SHORTCUT_COMMAND_KEY)
    if not isinstance(command, PlayerExtensionShortcutCommand):
        return "seer_player_extension"
    return command.action.action.cooldown_key or command.action.id


def _extension_shortcut_semantic_request(
    _service: PlayerService,
    _event: MessageEvent,
    state: T_State,
) -> SemanticRequest | None:
    command = state.get(_EXTENSION_SHORTCUT_COMMAND_KEY)
    if not isinstance(command, PlayerExtensionShortcutCommand):
        return None
    target = state.get(_EXTENSION_SHORTCUT_TARGET_KEY)
    player_id = (
        target.player_id
        if isinstance(target, PlayerTargetResolution)
        else command.player_id
    )
    if not (isinstance(player_id, int) and is_valid_player_id(player_id)):
        return None
    return SemanticRequest(
        action=command.action.action,
        target=player_shortcut_semantic_request(
            kind="collection",
            player_id=player_id,
            source=SemanticRequestSource.DIRECT,
        ).target,
        source=SemanticRequestSource.EXTENSION,
    )


def install(group: SeerMatcherGroup) -> None:
    dependencies = PlayerCommandDependencies(
        group.resources.player,
        group.features,
        group.resources.player_detail_extensions,
        group.player_accounts,
    )
    matcher = group.on_message(
        policy=CommandPolicy.command(
            _shortcut_command_id,
            help_ids=("seer.player.default",),
            semantic_request=lambda event, state: _shortcut_semantic_request(
                group.resources.player,
                event,
                state,
            ),
        ),
        rule=seer_feature_rule(group.features, "seer_player")
        & Rule(bind_async(_is_player_shortcut, dependencies=dependencies))
        & member_target_command(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    matcher.append_handler(
        bind_async(
            handle_player_shortcut,
            dependencies,
        )
    )

    extension_actions = dependencies.detail_extensions.actions()
    if not extension_actions:
        return

    extension_matcher = group.on_message(
        policy=CommandPolicy.command(
            _extension_shortcut_command_id,
            help_ids=tuple(action.command_help_id for action in extension_actions),
            semantic_request=lambda event, state: _extension_shortcut_semantic_request(
                group.resources.player,
                event,
                state,
            ),
        ),
        rule=Rule(
            bind_async(
                _is_player_extension_shortcut,
                dependencies=dependencies,
            )
        )
        & member_target_command(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    extension_matcher.append_handler(
        bind_async(handle_player_extension_shortcut, dependencies)
    )
