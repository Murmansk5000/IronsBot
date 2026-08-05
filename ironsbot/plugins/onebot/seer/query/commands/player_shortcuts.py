# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.runtime.feature_policy import event_is_feature_allowed
from ironsbot.runtime.matchers import CommandPolicy, bind_async
from ironsbot.runtime.message_input import message_input_context
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import member_target_command
from ironsbot.runtime.semantic_requests import (
    SemanticRequest,
    SemanticRequestSource,
)
from ironsbot.services.operations.request_feedback import request_feedback_scope
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailActionRequest,
)
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message
from ironsbot.services.seer.player_shortcuts import (
    PlayerShortcutCommand,
    PlayerShortcutTargetCommand,
    execute_player_shortcut,
    parse_player_shortcut_command,
    player_request_admission_message,
    player_shortcut_semantic_request,
)

from ..group import SeerMatcherGroup, seer_feature_rule
from .player import PlayerCommandDependencies
from .player_target import (
    event_player_reference_lookup,
    resolve_player_target,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.player_detail_extensions import (
        PlayerDetailExtensionAction,
    )
    from ironsbot.services.seer.query_result import QueryReply

_SHORTCUT_COMMAND_KEY = "_player_shortcut_command"
_EXTENSION_SHORTCUT_COMMAND_KEY = "_player_extension_shortcut_command"


@dataclass(frozen=True, slots=True)
class PlayerExtensionShortcutCommand:
    """A validated extension action and numeric player target."""

    action: PlayerDetailExtensionAction
    player_id: int


@dataclass(frozen=True, slots=True)
class PlayerExtensionShortcutTargetCommand:
    """An extension action plus its unresolved player reference."""

    action: PlayerDetailExtensionAction
    player_reference: str | None


@dataclass(frozen=True, slots=True)
class _ResolvedShortcutCommand:
    command: PlayerShortcutCommand | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _ResolvedExtensionShortcutCommand:
    command: PlayerExtensionShortcutCommand | None
    error: str | None = None


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
    if not isinstance(event, MessageEvent):
        return False
    command = parse_player_shortcut_command(event.get_plaintext())
    if command is None:
        return False
    state[_SHORTCUT_COMMAND_KEY] = _resolve_player_shortcut_command(
        dependencies,
        event,
        command,
    )
    return True


async def _is_player_extension_shortcut(
    event: Event,
    state: T_State,
    *,
    dependencies: PlayerCommandDependencies,
) -> bool:
    if not isinstance(event, MessageEvent):
        return False
    resolved = dependencies.detail_extensions.resolve_direct_command(
        event.get_plaintext()
    )
    if resolved is None:
        return False
    action, player_reference = resolved
    if not event_is_feature_allowed(dependencies.features, event, action.feature):
        return False
    state[_EXTENSION_SHORTCUT_COMMAND_KEY] = _resolve_extension_shortcut_command(
        dependencies,
        event,
        PlayerExtensionShortcutTargetCommand(
            action=action,
            player_reference=player_reference or None,
        ),
    )
    return True


def _resolve_player_shortcut_command(
    dependencies: PlayerCommandDependencies,
    event: MessageEvent,
    command: PlayerShortcutTargetCommand,
) -> _ResolvedShortcutCommand:
    target = resolve_player_target(
        event,
        player_reference=command.player_reference,
        reference_lookup=event_player_reference_lookup(
            dependencies.player_accounts,
            event,
        ),
        binding_for_user=dependencies.player.default_player_id,
    )
    if target.error is not None:
        return _ResolvedShortcutCommand(None, target.error)
    if target.player_id is None:
        return _ResolvedShortcutCommand(None, unbound_player_shortcut_message())
    return _ResolvedShortcutCommand(
        PlayerShortcutCommand(
            kind=command.kind,
            player_id=target.player_id,
        )
    )


def _resolve_extension_shortcut_command(
    dependencies: PlayerCommandDependencies,
    event: MessageEvent,
    command: PlayerExtensionShortcutTargetCommand,
) -> _ResolvedExtensionShortcutCommand:
    target = resolve_player_target(
        event,
        player_reference=command.player_reference,
        reference_lookup=event_player_reference_lookup(
            dependencies.player_accounts,
            event,
        ),
        binding_for_user=dependencies.player.default_player_id,
    )
    if target.error is not None:
        return _ResolvedExtensionShortcutCommand(None, target.error)
    if target.player_id is None:
        return _ResolvedExtensionShortcutCommand(
            None,
            unbound_player_shortcut_message(),
        )
    return _ResolvedExtensionShortcutCommand(
        PlayerExtensionShortcutCommand(
            action=command.action,
            player_id=target.player_id,
        )
    )


async def handle_player_shortcut(
    dependencies: PlayerCommandDependencies,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    service = dependencies.player
    resolved = state.get(_SHORTCUT_COMMAND_KEY)
    if not isinstance(resolved, _ResolvedShortcutCommand):
        return
    if resolved.error is not None:
        await finish_event_reply(matcher, event, resolved.error)
        return
    command = resolved.command
    if command is None:
        return

    async def send_status(message: str) -> None:
        await send_event_reply(matcher, event, message)

    reply = await execute_player_shortcut(
        service,
        command,
        message_input_context(event).message.actor,
        conversation=message_input_context(event).message.conversation,
        send_status=send_status,
    )
    await finish_event_reply(
        matcher,
        event,
        _build_shortcut_reply_message(reply),
    )


async def handle_player_extension_shortcut(
    _dependencies: PlayerCommandDependencies,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    resolved = state.get(_EXTENSION_SHORTCUT_COMMAND_KEY)
    if not isinstance(resolved, _ResolvedExtensionShortcutCommand):
        return
    if resolved.error is not None:
        await finish_event_reply(matcher, event, resolved.error)
        return
    command = resolved.command
    if command is None:
        return
    async def send_status(label: str, *, queued: bool) -> None:
        await send_event_reply(
            matcher,
            event,
            player_request_admission_message(label, queued=queued),
        )

    with request_feedback_scope(command.action.action.label, send_status):
        message = message_input_context(event).message
        reply = await command.action.query(
            PlayerDetailActionRequest(
                player_id=command.player_id,
                actor=message.actor,
                conversation=message.conversation,
            )
        )
    await finish_event_reply(matcher, event, _build_shortcut_reply_message(reply))


def _shortcut_command_id(
    _event: Event,
    state: T_State,
) -> str:
    command = state.get(_SHORTCUT_COMMAND_KEY)
    resolved = command if isinstance(command, _ResolvedShortcutCommand) else None
    kind = str(getattr(resolved.command, "kind", "")).strip() if resolved else ""
    return f"seer_player_{kind}" if kind else "seer_player"


def _shortcut_semantic_request(
    dependencies: PlayerCommandDependencies,
    event: MessageEvent,
    state: T_State,
) -> SemanticRequest | None:
    _ = dependencies, event
    resolved = state.get(_SHORTCUT_COMMAND_KEY)
    if not isinstance(resolved, _ResolvedShortcutCommand):
        return None
    command = resolved.command
    if command is None:
        return None
    return player_shortcut_semantic_request(
        kind=command.kind,
        player_id=command.player_id,
        source=SemanticRequestSource.DIRECT,
    )


def _extension_shortcut_command_id(
    _event: Event,
    state: T_State,
) -> str:
    command = state.get(_EXTENSION_SHORTCUT_COMMAND_KEY)
    resolved = (
        command
        if isinstance(command, _ResolvedExtensionShortcutCommand)
        else None
    )
    command = resolved.command if resolved is not None else None
    if command is None:
        return "seer_player_extension"
    return command.action.action.cooldown_key or command.action.id


def _extension_shortcut_semantic_request(
    dependencies: PlayerCommandDependencies,
    event: MessageEvent,
    state: T_State,
) -> SemanticRequest | None:
    _ = dependencies, event
    resolved = state.get(_EXTENSION_SHORTCUT_COMMAND_KEY)
    if not isinstance(resolved, _ResolvedExtensionShortcutCommand):
        return None
    command = resolved.command
    if command is None:
        return None
    return SemanticRequest(
        action=command.action.action,
        target=player_shortcut_semantic_request(
            kind="collection",
            player_id=command.player_id,
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
                dependencies,
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
            help_ids=tuple(
                action.command_help_id
                for action in extension_actions
            ),
            semantic_request=lambda event, state: _extension_shortcut_semantic_request(
                dependencies,
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
