# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (
    MessageEvent,
)
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.core.semantic_requests import (
    SemanticRequest,
    SemanticRequestSource,
)
from ironsbot.integrations.onebot.feature_policy import event_is_feature_allowed
from ironsbot.integrations.onebot.matchers import CommandPolicy, bind_async
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import member_target_command
from ironsbot.services.player_extension_commands import build_player_extension_operation
from ironsbot.services.portable_player_commands import build_portable_player_operations
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message
from ironsbot.services.seer.player_shortcut_contracts import (
    PlayerShortcutCommand,
    PlayerShortcutTargetCommand,
    parse_player_shortcut_command,
    player_shortcut_semantic_request,
)

from ..group import SeerMatcherGroup, seer_feature_rule
from .player import PlayerCommandDependencies
from .player_target import resolve_player_target

if TYPE_CHECKING:
    from ironsbot.services.seer.player_detail_extensions import (
        PlayerDetailExtensionAction,
    )

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
        resolver=dependencies.player_id_resolver,
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
        resolver=dependencies.player_id_resolver,
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
        command if isinstance(command, _ResolvedExtensionShortcutCommand) else None
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
        group.player_id_resolver,
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
        make_portable_query_handler(
            build_portable_player_operations(
                group.resources.player,
                group.player_id_resolver,
                group.query_sessions,
                group.features,
                group.resources.player_detail_extensions,
            )["seer.player.default"],
            group.query_sessions,
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
        make_portable_query_handler(
            build_player_extension_operation(
                group.resources.player_detail_extensions,
                group.player_id_resolver,
                group.features,
            ),
            group.query_sessions,
        )
    )
