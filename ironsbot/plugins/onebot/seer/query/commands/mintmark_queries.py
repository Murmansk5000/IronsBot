# SPDX-License-Identifier: GPL-3.0-or-later
"""Mintmark and gem query matchers."""

from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import affix_command, explicit_command
from ironsbot.services.seer.query_commands import GEM_QUERY, MINTMARK_QUERY

from ..group import SeerMatcherGroup, seer_feature_rule


def install(group: SeerMatcherGroup) -> None:
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
            group.operation("seer.mintmark.query"), group.query_sessions
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
            group.operation("seer.mintmark.query"), group.query_sessions
        )
    )
