# SPDX-License-Identifier: GPL-3.0-or-later
"""OneBot registrations for the shared peak operations."""

from __future__ import annotations

from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.portable_seer_commands import (
    build_peak_query_operation,
    build_peak_rank_operation,
)
from ironsbot.services.seer.peak import (
    PEAK_EXPERT_POOL_COMMANDS,
    PEAK_MASTER_POOL_COMMANDS,
    PEAK_PET_RANK_COMMANDS,
    PEAK_POOL_COMMANDS,
    PEAK_SUIT_RANK_COMMANDS,
    PEAK_TITLE_RANK_COMMANDS,
    PEAK_VOTE_COMMANDS,
)

from ..group import SeerMatcherGroup, seer_feature_rule


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.peak_query
    query = build_peak_query_operation(service)
    rank = build_peak_rank_operation(service)
    rule = seer_feature_rule(group.features, "seer_peak") & explicit_command()
    for commands, command_id, help_id, operation in (
        (PEAK_POOL_COMMANDS, "seer_peak_pool", "seer.peak.query", query),
        (PEAK_EXPERT_POOL_COMMANDS, "seer_peak_expert_pool", "seer.peak.query", query),
        (PEAK_MASTER_POOL_COMMANDS, "seer_peak_master_pool", "seer.peak.query", query),
        (PEAK_VOTE_COMMANDS, "seer_peak_vote", "seer.peak.query", query),
        (PEAK_SUIT_RANK_COMMANDS, "seer_peak_suit_rank", "seer.peak.rank", rank),
        (PEAK_TITLE_RANK_COMMANDS, "seer_peak_title_rank", "seer.peak.rank", rank),
        (PEAK_PET_RANK_COMMANDS, "seer_peak_pet_rank", "seer.peak.rank", rank),
    ):
        matcher = group.on_fullmatch(
            commands,
            policy=CommandPolicy.command(command_id, help_ids=(help_id,)),
            rule=rule,
            priority=group.matcher_priority("seer_peak"),
        )
        matcher.append_handler(
            make_portable_query_handler(operation, group.query_sessions)
        )
