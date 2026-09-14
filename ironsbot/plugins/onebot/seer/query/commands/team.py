# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ironsbot.integrations.onebot.matchers import CommandPolicy, bind_async
from ironsbot.integrations.onebot.replies import run_portable_operation
from ironsbot.integrations.onebot.rules import affix_command, explicit_command
from ironsbot.services.portable_seer_commands import (
    build_portable_team_query_operation,
)
from ironsbot.services.seer.query_commands import team_query_input

from ..group import SeerMatcherGroup, seer_feature_rule


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.team_query
    operation = build_portable_team_query_operation(service, group.features)
    matcher = group.on_message(
        policy=CommandPolicy.command("seer_team", help_ids=("seer.team.query",)),
        rule=seer_feature_rule(group.features, "seer_team")
        & affix_command(team_query_input)
        & explicit_command(),
        priority=group.matcher_priority("seer_team"),
    )
    matcher.append_handler(
        bind_async(run_portable_operation, operation=operation)
    )
