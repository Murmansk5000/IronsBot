# SPDX-License-Identifier: GPL-3.0-or-later
"""Seer data query matchers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
)
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.portable_data_commands import build_portable_data_operation
from ironsbot.services.seer.data_query_commands import (
    DATA_VERSION_COMMANDS,
    SEASON_COUNTDOWN_COMMANDS,
    WEEKLY_PREVIEW_COMMANDS,
)
from ironsbot.services.seer.external_references import SeerInfoReference

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from ironsbot.services.seer.data_queries import SeerDataQueryService


def install(group: SeerMatcherGroup) -> None:
    service: SeerDataQueryService = group.resources.data_queries
    references = getattr(group.resources, "external_references", None)
    commands = (
        (
            WEEKLY_PREVIEW_COMMANDS,
            "seer_data_preview",
            service.weekly_preview,
            SeerInfoReference.WEEKLY_PREVIEW,
        ),
        (DATA_VERSION_COMMANDS, "seer_data_version", service.data_version, None),
        (
            SEASON_COUNTDOWN_COMMANDS,
            "seer_season_countdown",
            service.season_countdown,
            None,
        ),
    )
    rule = seer_feature_rule(group.features, "seer_data") & explicit_command()
    for messages, command_id, _operation, _reference in commands:
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
            make_portable_query_handler(
                build_portable_data_operation(service, references), group.query_sessions
            )
        )
