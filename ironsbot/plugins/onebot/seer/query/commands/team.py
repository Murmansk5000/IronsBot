# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from nonebot.adapters.onebot.v11 import (
    MessageEvent,  # noqa: TC002 - NoneBot resolves annotations
)
from nonebot.rule import Rule

from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.integrations.onebot.matchers import CommandPolicy, bind_async
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.replies import run_portable_operation
from ironsbot.integrations.onebot.rules import member_target_command
from ironsbot.services.portable_seer_commands import (
    build_portable_team_query_operation,
)
from ironsbot.services.seer.query_commands import team_query_input_matcher

from ..group import SeerMatcherGroup, seer_feature_rule


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.team_query
    operation = build_portable_team_query_operation(
        service, group.features, group.player_id_resolver
    )
    matches = team_query_input_matcher(group.player_id_resolver.has_known_reference)

    def owns_input(event: MessageEvent) -> bool:
        context = message_input_context(event)
        return matches(context.text, command_context_from_input(context))

    matcher = group.on_message(
        policy=CommandPolicy.command("seer_team", help_ids=("seer.team.query",)),
        rule=seer_feature_rule(group.features, "seer_team")
        & Rule(owns_input)
        & member_target_command(),
        priority=group.matcher_priority("seer_team"),
    )
    matcher.append_handler(bind_async(run_portable_operation, operation=operation))
