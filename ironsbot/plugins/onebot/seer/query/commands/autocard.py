# SPDX-License-Identifier: GPL-3.0-or-later
"""OneBot registration for shared Autocard menu operations."""

from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.rules import affix_command, explicit_command
from ironsbot.services.seer.query_commands import AUTOCARD_QUERY

from ..group import SeerMatcherGroup, seer_feature_rule


def install(group: SeerMatcherGroup) -> None:
    from ironsbot.integrations.onebot.portable_queries import (
        make_portable_query_handler,
    )
    from ironsbot.services.portable_autocard_commands import (
        build_portable_autocard_operations,
    )

    operations = build_portable_autocard_operations(
        group.resources.autocard,
        group.resources.autocard_media,
        group.resources.autocard_sanctuary,
        group.query_sessions,
    )
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
            operations["seer.autocard.query"], group.query_sessions
        )
    )
