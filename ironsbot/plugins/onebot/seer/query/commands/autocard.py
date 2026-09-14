# SPDX-License-Identifier: GPL-3.0-or-later
"""OneBot transport boundary for Autocard queries."""

from __future__ import annotations

from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import affix_command, explicit_command
from ironsbot.services.portable_autocard_commands import (
    build_portable_autocard_operations,
)
from ironsbot.services.seer.query_commands import AUTOCARD_QUERY

from ..group import SeerMatcherGroup, seer_feature_rule


def install(group: SeerMatcherGroup) -> None:
    operation = build_portable_autocard_operations(
        group.resources.autocard,
        group.resources.autocard_media,
        group.resources.autocard_sanctuary,
        group.query_sessions,
    )["seer.autocard.query"]
    matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_autocard_query",
            help_ids=("seer.autocard.query",),
        ),
        rule=seer_feature_rule(group.features, "seer_autocard")
        & affix_command(AUTOCARD_QUERY)
        & explicit_command(),
        priority=group.matcher_priority("seer_autocard"),
    )
    matcher.append_handler(
        make_portable_query_handler(
            operation,
            group.query_sessions,
            ActionDefinition("seer_autocard_query", "群星牌查询"),
        )
    )
