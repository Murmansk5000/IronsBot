# SPDX-License-Identifier: GPL-3.0-or-later
"""Mintmark and gem query matchers."""

from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import affix_command, explicit_command
from ironsbot.services.portable_seer_commands import (
    build_portable_mintmark_query_operations,
)
from ironsbot.services.seer.query_commands import GEM_QUERY, MINTMARK_QUERY

from ..group import SeerMatcherGroup, seer_feature_rule


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.mintmark
    operation = build_portable_mintmark_query_operations(
        service,
        group.query_sessions,
    )["seer.mintmark.query"]
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
        make_portable_query_handler(
            operation,
            group.query_sessions,
            ActionDefinition("seer_mintmark_query", "刻印查询"),
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
        make_portable_query_handler(
            operation,
            group.query_sessions,
            ActionDefinition("seer_gem_query", "宝石查询"),
        )
    )
