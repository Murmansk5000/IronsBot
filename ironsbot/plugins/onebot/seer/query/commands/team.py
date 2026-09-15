# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from nonebot.adapters.onebot.v11 import (
    MessageEvent,  # noqa: TC002 - NoneBot resolves it at runtime
)
from nonebot.rule import Rule

from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import member_targets_command
from ironsbot.services.seer.query_commands import team_query_input_matcher
from ironsbot.services.seer.team_commands import build_team_query_operation

from ..group import SeerMatcherGroup, seer_feature_rule


def install(group: SeerMatcherGroup) -> None:
    input_matches = team_query_input_matcher(
        group.player_id_resolver.has_reference_choices
    )

    def is_team_query(event: MessageEvent) -> bool:
        context = message_input_context(event)
        return input_matches(context.text, command_context_from_input(context))

    matcher = group.on_message(
        policy=CommandPolicy.command("seer_team", help_ids=("seer.team.query",)),
        rule=seer_feature_rule(group.features, "seer_team")
        & Rule(is_team_query)
        & member_targets_command(),
        priority=group.matcher_priority("seer_team"),
    )
    matcher.append_handler(
        make_portable_query_handler(
            build_team_query_operation(
                group.resources.team_query,
                group.player_id_resolver,
                group.features,
                group.query_sessions,
            ),
            group.query_sessions,
        )
    )
