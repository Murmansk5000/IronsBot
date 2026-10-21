# SPDX-License-Identifier: GPL-3.0-or-later
"""Element type and battle effect query matchers."""

from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import affix_command, explicit_command
from ironsbot.services.seer.query_commands import BATTLE_EFFECT_QUERY, TYPE_QUERY

from ..group import SeerMatcherGroup, seer_feature_rule


def install(group: SeerMatcherGroup) -> None:
    type_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_type_query",
            help_ids=("seer.type.query",),
        ),
        rule=seer_feature_rule(group.features, "seer_type")
        & affix_command(TYPE_QUERY)
        & explicit_command(),
        priority=group.matcher_priority("seer_type"),
    )
    type_matcher.append_handler(
        make_portable_query_handler(
            group.operation("seer.type.query"), group.query_sessions
        )
    )

    effect_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_battle_effect_query",
            help_ids=("seer.type.query",),
        ),
        rule=seer_feature_rule(group.features, "seer_type")
        & affix_command(BATTLE_EFFECT_QUERY)
        & explicit_command(),
        priority=group.matcher_priority("seer_type"),
    )
    effect_matcher.append_handler(
        make_portable_query_handler(
            group.operation("seer.type.query"), group.query_sessions
        )
    )
