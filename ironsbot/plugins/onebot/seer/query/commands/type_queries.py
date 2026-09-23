# SPDX-License-Identifier: GPL-3.0-or-later
"""Element type and battle effect query matchers."""

from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.rules import affix_command, explicit_command
from ironsbot.services.seer.query_commands import BATTLE_EFFECT_QUERY, TYPE_QUERY

from ..group import SeerMatcherGroup, seer_feature_rule
from ..query_conversation import make_query_handler


def install(group: SeerMatcherGroup) -> None:
    type_service = group.resources.type_query
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
        make_query_handler(
            type_service.search,
            type_service.select,
            "请问你想查询的属性是……",
            ActionDefinition("seer_type_query", "属性查询"),
            sessions=group.query_sessions,
        )
    )

    effect_service = group.resources.battle_effect
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
        make_query_handler(
            effect_service.search,
            effect_service.select,
            "请问你想查询的异常状态是……",
            ActionDefinition("seer_battle_effect_query", "异常状态查询"),
            sessions=group.query_sessions,
        )
    )
