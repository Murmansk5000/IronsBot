# SPDX-License-Identifier: GPL-3.0-or-later
"""OneBot transport boundary for weekly release-content queries."""

from __future__ import annotations

from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.portable_new_content_commands import (
    build_portable_new_content_operations,
)
from ironsbot.services.seer.data_query_commands import (
    NEW_CONTENT_COMMAND_SPECS,
    NEW_CONTENT_COMMANDS,
)

from ..group import SeerMatcherGroup, seer_feature_rule


def install(group: SeerMatcherGroup) -> None:
    operations = build_portable_new_content_operations(
        group.resources,
        group.query_sessions,
        group.features,
        expanded_categories=group.new_content_expanded_categories,
        preview_max_items=group.new_content_preview_max_items,
    )
    base_rule = seer_feature_rule(group.features, "seer_data") & explicit_command()
    priority = group.matcher_priority("seer_data")

    root = group.on_fullmatch(
        NEW_CONTENT_COMMANDS,
        policy=CommandPolicy.command(
            "seer.data.new_content",
            help_ids=("seer.data.new_content",),
        ),
        rule=base_rule,
        priority=priority,
    )
    root.append_handler(
        make_portable_query_handler(
            operations["seer.data.new_content"],
            group.query_sessions,
            ActionDefinition("seer.data.new_content", "新增内容"),
        )
    )

    for spec in NEW_CONTENT_COMMAND_SPECS:
        rule = base_rule
        for feature in spec.required_features:
            rule &= seer_feature_rule(group.features, feature)
        matcher = group.on_fullmatch(
            spec.commands,
            policy=CommandPolicy.command(
                spec.command_id,
                help_ids=(spec.command_id,),
            ),
            rule=rule,
            priority=priority,
        )
        matcher.append_handler(
            make_portable_query_handler(
                operations[spec.command_id],
                group.query_sessions,
                ActionDefinition(spec.command_id, spec.description),
            )
        )
