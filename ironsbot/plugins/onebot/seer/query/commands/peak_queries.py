# SPDX-License-Identifier: GPL-3.0-or-later
"""Peak query matchers."""

from __future__ import annotations

from ironsbot.integrations.onebot.matchers import CommandPolicy, bind_async
from ironsbot.integrations.onebot.replies import run_portable_operation
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.portable_seer_commands import (
    build_portable_peak_query_operation,
    build_portable_peak_rank_operation,
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
    query_operation = build_portable_peak_query_operation(service)
    rank_operation = build_portable_peak_rank_operation(service)
    rule = seer_feature_rule(group.features, "seer_peak") & explicit_command()
    priority = group.matcher_priority("seer_peak")

    pool = group.on_fullmatch(
        PEAK_POOL_COMMANDS,
        policy=CommandPolicy.command(
            "seer_peak_pool",
            help_ids=("seer.peak.query",),
        ),
        rule=rule,
        priority=priority,
    )
    pool.append_handler(
        bind_async(run_portable_operation, operation=query_operation)
    )

    expert_pool = group.on_fullmatch(
        PEAK_EXPERT_POOL_COMMANDS,
        policy=CommandPolicy.command(
            "seer_peak_expert_pool",
            help_ids=("seer.peak.query",),
        ),
        rule=rule,
        priority=priority,
    )
    expert_pool.append_handler(
        bind_async(run_portable_operation, operation=query_operation)
    )

    master_pool = group.on_fullmatch(
        PEAK_MASTER_POOL_COMMANDS,
        policy=CommandPolicy.command(
            "seer_peak_master_pool",
            help_ids=("seer.peak.query",),
        ),
        rule=rule,
        priority=priority,
    )
    master_pool.append_handler(
        bind_async(run_portable_operation, operation=query_operation)
    )

    vote = group.on_fullmatch(
        PEAK_VOTE_COMMANDS,
        policy=CommandPolicy.command(
            "seer_peak_vote",
            help_ids=("seer.peak.query",),
        ),
        rule=rule,
        priority=priority,
    )
    vote.append_handler(
        bind_async(run_portable_operation, operation=query_operation)
    )

    suit = group.on_fullmatch(
        PEAK_SUIT_RANK_COMMANDS,
        policy=CommandPolicy.command(
            "seer_peak_suit_rank",
            help_ids=("seer.peak.rank",),
        ),
        rule=rule,
        priority=priority,
    )
    suit.append_handler(
        bind_async(run_portable_operation, operation=rank_operation)
    )

    title = group.on_fullmatch(
        PEAK_TITLE_RANK_COMMANDS,
        policy=CommandPolicy.command(
            "seer_peak_title_rank",
            help_ids=("seer.peak.rank",),
        ),
        rule=rule,
        priority=priority,
    )
    title.append_handler(
        bind_async(run_portable_operation, operation=rank_operation)
    )

    pet = group.on_fullmatch(
        PEAK_PET_RANK_COMMANDS,
        policy=CommandPolicy.command(
            "seer_peak_pet_rank",
            help_ids=("seer.peak.rank",),
        ),
        rule=rule,
        priority=priority,
    )
    pet.append_handler(
        bind_async(run_portable_operation, operation=rank_operation)
    )
