# SPDX-License-Identifier: GPL-3.0-or-later
"""Element type and battle effect query matchers."""

from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.runtime.rules import explicit_command, startswith_or_endswith
from ironsbot.runtime.semantic_requests import ActionDefinition

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
        & startswith_or_endswith("属性")
        & explicit_command(),
        priority=group.matcher_priority("seer_type"),
    )
    type_matcher.append_handler(
        make_query_handler(
            type_service.search,
            type_service.select,
            "请问你想查询的属性是……",
            ActionDefinition("seer_type_query", "属性查询"),
        )
    )

    effect_service = group.resources.battle_effect
    effect_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_battle_effect_query",
            help_ids=("seer.type.query",),
        ),
        rule=seer_feature_rule(group.features, "seer_type")
        & startswith_or_endswith(
            ("异常", "查询异常状态"),
            suffixes="异常",
        )
        & explicit_command(),
        priority=group.matcher_priority("seer_type"),
    )
    effect_matcher.append_handler(
        make_query_handler(
            effect_service.search,
            effect_service.select,
            "请问你想查询的异常状态是……",
            ActionDefinition("seer_battle_effect_query", "异常状态查询"),
        )
    )
