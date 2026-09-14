# SPDX-License-Identifier: GPL-3.0-or-later
"""Seer data query matchers."""

from __future__ import annotations

from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    bind_async,
)
from ironsbot.integrations.onebot.replies import run_portable_operation
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.portable_seer_commands import (
    build_portable_data_query_operation,
)
from ironsbot.services.seer.data_query_commands import (
    DATA_VERSION_COMMANDS,
    SEASON_COUNTDOWN_COMMANDS,
    WEEKLY_PREVIEW_COMMANDS,
)

from ..group import SeerMatcherGroup, seer_feature_rule


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.data_queries
    references = getattr(group.resources, "external_references", None)
    operation = build_portable_data_query_operation(service, references)
    commands = (
        (WEEKLY_PREVIEW_COMMANDS, "seer_data_preview"),
        (DATA_VERSION_COMMANDS, "seer_data_version"),
        (SEASON_COUNTDOWN_COMMANDS, "seer_season_countdown"),
    )
    rule = seer_feature_rule(group.features, "seer_data") & explicit_command()
    for messages, command_id in commands:
        matcher = group.on_fullmatch(
            messages,
            policy=CommandPolicy.command(
                command_id,
                help_ids=("seer.data.query",),
            ),
            rule=rule,
            priority=group.matcher_priority("seer_data"),
        )
        matcher.append_handler(
            bind_async(run_portable_operation, operation=operation)
        )
