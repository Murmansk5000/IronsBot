# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (
    MessageEvent,
)
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.core.player_reference_commands import is_player_reference_input
from ironsbot.integrations.onebot.matcher_support import bind_async
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import member_target_command
from ironsbot.services.player_extension_commands import build_player_extension_operation
from ironsbot.services.portable_player_commands import build_portable_player_operations
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionRegistry,
    extension_action_allowed,
)
from ironsbot.services.seer.player_shortcut_contracts import (
    PlayerShortcutTargetCommand,
    parse_player_shortcut_command,
)

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.seer.player_detail_extensions import (
        PlayerDetailExtensionAction,
    )
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.player_service import PlayerService

_SHORTCUT_COMMAND_KEY = "_player_shortcut_command"
_EXTENSION_SHORTCUT_COMMAND_KEY = "_player_extension_shortcut_command"


@dataclass(frozen=True, slots=True)
class PlayerCommandDependencies:
    player: PlayerService
    features: FeatureService
    detail_extensions: PlayerDetailExtensionRegistry = field(
        default_factory=PlayerDetailExtensionRegistry
    )
    player_id_resolver: PlayerIdResolver | None = None


@dataclass(frozen=True, slots=True)
class PlayerExtensionShortcutTargetCommand:
    """An extension action plus its unresolved player reference."""

    action: PlayerDetailExtensionAction
    player_reference: str | None


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
    if command.player_reference and not _known_target(
        command.player_reference, event, dependencies.player_id_resolver
    ):
        return False
    state[_SHORTCUT_COMMAND_KEY] = command
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
    if player_reference and not _known_target(
        player_reference, event, dependencies.player_id_resolver
    ):
        return False
    if not extension_action_allowed(
        action, message_input_context(event), dependencies.features
    ):
        return False
    state[_EXTENSION_SHORTCUT_COMMAND_KEY] = PlayerExtensionShortcutTargetCommand(
        action=action, player_reference=player_reference or None
    )
    return True


def _known_target(
    reference: str, event: MessageEvent, resolver: PlayerIdResolver | None
) -> bool:
    context = message_input_context(event)
    return is_player_reference_input(
        reference,
        command_context_from_input(context),
        resolver.has_reference_choices if resolver is not None else lambda *_: False,
    )


def _shortcut_command_id(_event: Event, state: T_State) -> str:
    command = state.get(_SHORTCUT_COMMAND_KEY)
    return (
        f"seer_player_{command.kind}"
        if isinstance(command, PlayerShortcutTargetCommand)
        else "seer_player"
    )


def _extension_shortcut_command_id(_event: Event, state: T_State) -> str:
    command = state.get(_EXTENSION_SHORTCUT_COMMAND_KEY)
    if not isinstance(command, PlayerExtensionShortcutTargetCommand):
        return "seer_player_extension"
    return command.action.action.cooldown_key or command.action.id


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
            semantic_request=lambda _event, _state: None,
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
                group.resources.rank_queries,
                menu_actions=group.resources.player_menu_actions,
                nickname_lookup=group.resources.player_nickname_lookup,
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
            semantic_request=lambda _event, _state: None,
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
                group.query_sessions,
                group.resources.player,
            ),
            group.query_sessions,
        )
    )
