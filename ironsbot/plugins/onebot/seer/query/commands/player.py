# SPDX-License-Identifier: GPL-3.0-or-later
"""OneBot transport boundary for player profiles and bindings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot.matchers import CommandPolicy, bind_async
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import explicit_command, member_target_command
from ironsbot.services.portable_player_commands import build_portable_player_operations
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_query import (
    extract_player_binding_arg,
    extract_player_query_arg,
)

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.player_service import PlayerService


@dataclass(frozen=True, slots=True)
class PlayerCommandDependencies:
    player: PlayerService
    features: FeatureService
    detail_extensions: PlayerDetailExtensionRegistry = field(
        default_factory=PlayerDetailExtensionRegistry
    )
    player_id_resolver: PlayerIdResolver | None = None


async def _is_player_id_query(
    dependencies: PlayerCommandDependencies,
    event: Event,
    _state: T_State,
) -> bool:
    if not isinstance(event, MessageEvent):
        return False
    argument = extract_player_query_arg(event.get_plaintext())
    if argument is None:
        return False
    if not argument or argument.isdecimal():
        return True
    resolver = dependencies.player_id_resolver
    context = message_input_context(event)
    return resolver is not None and resolver.has_known_reference(
        argument,
        context.message.actor,
        context.message.conversation,
    )


async def _is_binding_command(event: Event, _state: T_State) -> bool:
    return (
        isinstance(event, MessageEvent)
        and extract_player_binding_arg(event.get_plaintext()) is not None
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
        dependencies.detail_extensions,
        team_query=group.resources.team_query,
    )
    feature_rule = seer_feature_rule(group.features, "seer_player")
    priority = group.matcher_priority("seer_player")

    binding = group.on_message(
        policy=CommandPolicy.command(
            "seer_player_binding",
            help_ids=("seer.player.bind",),
        ),
        rule=feature_rule & Rule(_is_binding_command) & member_target_command(),
        priority=priority,
        block=True,
    )
    binding.append_handler(
        make_portable_query_handler(
            operations["seer.player.bind"],
            group.query_sessions,
            ActionDefinition("seer.player.bind", "绑定米米号"),
        )
    )

    unbind = group.on_fullmatch(
        ("解绑米米号",),
        policy=CommandPolicy.command(
            "seer_player_binding",
            help_ids=("seer.player.unbind",),
        ),
        rule=feature_rule & explicit_command(),
        priority=priority,
        block=True,
    )
    unbind.append_handler(
        make_portable_query_handler(
            operations["seer.player.unbind"],
            group.query_sessions,
            ActionDefinition("seer.player.unbind", "解绑米米号"),
            reserve_session=False,
        )
    )

    query = group.on_message(
        policy=CommandPolicy.command(
            "seer_player",
            help_ids=("seer.player.query",),
        ),
        rule=feature_rule
        & Rule(bind_async(_is_player_id_query, dependencies=dependencies))
        & member_target_command(),
        priority=priority,
        block=True,
    )
    query.append_handler(
        make_portable_query_handler(
            operations["seer.player.query"],
            group.query_sessions,
            ActionDefinition(
                "seer.player.info",
                "米米号基础资料",
                cooldown_key="seer_player",
            ),
        )
    )
