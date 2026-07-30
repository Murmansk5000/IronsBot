# SPDX-License-Identifier: GPL-3.0-or-later
"""Mintmark and gem query matchers."""

from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.runtime.rules import no_reply, startswith_or_endswith
from ironsbot.runtime.semantic_requests import ActionDefinition

from ..group import SeerMatcherGroup, seer_feature_rule
from ..query_conversation import make_query_handler
from .query_rules import not_rank_query


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.mintmark
    mintmark_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_mintmark_query",
            help_ids=("seer.mintmark.query",),
        ),
        rule=seer_feature_rule(group.features, "seer_mintmark")
        & startswith_or_endswith("刻印")
        & not_rank_query
        & no_reply(),
        priority=group.matcher_priority("seer_mintmark"),
    )
    mintmark_matcher.append_handler(
        make_query_handler(
            service.search_mintmark,
            service.select_mintmark,
            "请问你想查询的刻印是……",
            ActionDefinition("seer_mintmark_query", "刻印查询"),
        )
    )

    gem_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_gem_query",
            help_ids=("seer.mintmark.query",),
        ),
        rule=seer_feature_rule(group.features, "seer_mintmark")
        & startswith_or_endswith("宝石")
        & no_reply(),
        priority=group.matcher_priority("seer_mintmark"),
    )
    gem_matcher.append_handler(
        make_query_handler(
            service.search_gem,
            service.select_gem,
            "请问你想查询的宝石是……",
            ActionDefinition("seer_gem_query", "宝石查询"),
        )
    )
