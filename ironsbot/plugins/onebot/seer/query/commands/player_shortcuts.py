# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from functools import partial
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
from ironsbot.integrations.onebot.matchers import CommandPolicy, bind_async
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.portable_queries import (
    make_portable_query_handler,
)
from ironsbot.integrations.onebot.rules import member_target_command
from ironsbot.services.portable_player_commands import (
    build_portable_player_operations,
    resolve_portable_player_extension,
    resolve_portable_player_shortcut,
)
from ironsbot.services.seer.player_shortcut_contracts import (
    PLAYER_SHORTCUT_ACTIONS,
    parse_player_shortcut_command,
    player_semantic_target,
    player_shortcut_semantic_request,
)

from ..group import SeerMatcherGroup, seer_feature_rule
from .player import PlayerCommandDependencies

if TYPE_CHECKING:
    from ironsbot.services.seer.player_detail_extensions import (
        PlayerDetailExtensionAction,
    )


async def _is_player_shortcut(
    event: Event,
    *,
    dependencies: PlayerCommandDependencies,
) -> bool:
    if not isinstance(event, MessageEvent):
        return False
    resolver = dependencies.player_id_resolver
    return (
        resolver is not None
        and resolve_portable_player_shortcut(
            event.get_plaintext(),
            message_input_context(event),
            resolver,
        )
        is not None
    )


async def _is_player_extension_shortcut(
    event: Event,
    *,
    dependencies: PlayerCommandDependencies,
    action: PlayerDetailExtensionAction,
) -> bool:
    if not isinstance(event, MessageEvent):
        return False
    resolver = dependencies.player_id_resolver
    if resolver is None:
        return False
    resolved = resolve_portable_player_extension(
        event.get_plaintext(),
        message_input_context(event),
        resolver,
        dependencies.detail_extensions,
    )
    return resolved is not None and resolved.action.id == action.id


def _extension_shortcut_semantic_request(
    dependencies: PlayerCommandDependencies,
    action: PlayerDetailExtensionAction,
    event: Event,
    state: T_State,
) -> SemanticRequest | None:
    del state
    resolver = dependencies.player_id_resolver
    if resolver is None or not isinstance(event, MessageEvent):
        return None
    resolved = resolve_portable_player_extension(
        event.get_plaintext(),
        message_input_context(event),
        resolver,
        dependencies.detail_extensions,
    )
    if (
        resolved is None
        or resolved.action.id != action.id
        or resolved.player_id is None
    ):
        return None
    return SemanticRequest(
        action=action.action,
        target=player_semantic_target(resolved.player_id),
        source=SemanticRequestSource.EXTENSION,
    )


def _shortcut_command_id(
    event: Event,
    _state: T_State,
) -> str:
    if not isinstance(event, MessageEvent):
        return "seer_player"
    parsed = parse_player_shortcut_command(event.get_plaintext())
    kind = parsed.kind if parsed is not None else ""
    return f"seer_player_{kind}" if kind else "seer_player"


def _shortcut_semantic_request(
    dependencies: PlayerCommandDependencies,
    event: MessageEvent,
    state: T_State,
) -> SemanticRequest | None:
    del state
    resolver = dependencies.player_id_resolver
    if resolver is None:
        return None
    resolved = resolve_portable_player_shortcut(
        event.get_plaintext(),
        message_input_context(event),
        resolver,
    )
    command = resolved.command if resolved is not None else None
    if command is None:
        return None
    return player_shortcut_semantic_request(
        kind=command.kind,
        player_id=command.player_id,
        source=SemanticRequestSource.DIRECT,
    )


def install(group: SeerMatcherGroup) -> None:
    dependencies = PlayerCommandDependencies(
        group.resources.player,
        group.features,
        group.resources.player_detail_extensions,
        group.player_id_resolver,
    )
    operations = build_portable_player_operations(
        dependencies.player,
        group.player_id_resolver,
        group.query_sessions,
        group.features,
        group.resources.player_detail_extensions,
    )
    adapter = make_portable_query_handler(
        operations["seer.player.default"],
        group.query_sessions,
        PLAYER_SHORTCUT_ACTIONS["collection"],
        reserve_session=False,
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
    matcher.append_handler(adapter)

    extension_actions = dependencies.detail_extensions.actions()
    if not extension_actions:
        return

    for action in extension_actions:
        extension_matcher = group.on_message(
            policy=CommandPolicy.command(
                action.action.cooldown_key or action.id,
                help_ids=(action.command_help_id,),
                semantic_request=partial(
                    _extension_shortcut_semantic_request,
                    dependencies,
                    action,
                ),
            ),
            rule=seer_feature_rule(group.features, action.feature)
            & Rule(
                bind_async(
                    _is_player_extension_shortcut,
                    dependencies=dependencies,
                    action=action,
                )
            )
            & member_target_command(),
            priority=group.matcher_priority("seer_player"),
            block=True,
        )
        extension_matcher.append_handler(
            make_portable_query_handler(
                operations[action.command_help_id],
                group.query_sessions,
                action.action,
                reserve_session=False,
            )
        )
