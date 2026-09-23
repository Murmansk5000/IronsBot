# SPDX-License-Identifier: GPL-3.0-or-later
"""Mintmark and gem query matchers."""

from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.rules import affix_command, explicit_command
from ironsbot.services.seer.query_commands import GEM_QUERY, MINTMARK_QUERY

from ..group import SeerMatcherGroup, seer_feature_rule
from ..query_conversation import make_query_handler


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.mintmark
    mintmark_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_mintmark_query",
            help_ids=("seer.mintmark.query",),
        ),
        rule=seer_feature_rule(group.features, "seer_mintmark")
        & affix_command(MINTMARK_QUERY)
        & explicit_command(),
        priority=group.matcher_priority("seer_mintmark"),
    )
    mintmark_matcher.append_handler(
        make_query_handler(
            service.search_mintmark,
            service.select_mintmark,
            "请问你想查询的刻印是……",
            ActionDefinition("seer_mintmark_query", "刻印查询"),
            sessions=group.query_sessions,
        )
    )

    gem_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_gem_query",
            help_ids=("seer.mintmark.query",),
        ),
        rule=seer_feature_rule(group.features, "seer_mintmark")
        & affix_command(GEM_QUERY)
        & explicit_command(),
        priority=group.matcher_priority("seer_mintmark"),
    )
    gem_matcher.append_handler(
        make_query_handler(
            service.search_gem,
            service.select_gem,
            "请问你想查询的宝石是……",
            ActionDefinition("seer_gem_query", "宝石查询"),
            sessions=group.query_sessions,
        )
    )
