# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (  # noqa: TC002 - NoneBot resolves it at runtime
    MessageEvent,
)
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule

from ironsbot.integrations.onebot.matchers import CommandPolicy, bind, bind_async
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.replies import run_portable_operation
from ironsbot.integrations.onebot.rules import explicit_command, member_target_command
from ironsbot.services.portable_rank_commands import (
    build_portable_rank_admin_operations,
    build_portable_rank_display_operation,
    build_portable_rank_query_operation,
)
from ironsbot.services.seer.rank_display import parse_rank_display_limit_command
from ironsbot.services.seer.rank_list_models import (
    RANK_PAGE_OVERVIEW_COMMANDS,
    RANK_SAMPLE_REFRESH_COMMANDS,
    RANK_SAMPLE_STATUS_COMMANDS,
)
from ironsbot.services.seer.rank_list_parsing import (
    parse_rank_cache_batch_command,
    parse_rank_list_command,
    parse_rank_page_cache_refresh_command,
    parse_rank_page_cache_status_command,
    parse_rank_player_target_command,
    parse_rank_score_command,
)

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.services.seer.rank_queries import RankQueryService


def _is_rank_list_command(
    service: RankQueryService,
    event: Event,
) -> bool:
    return parse_rank_list_command(
        event.get_plaintext(),
        default_limit=service.default_limit(
            message_input_context(event).message.conversation
        ),
    ) is not None


def _is_rank_player_command(
    event: MessageEvent,
) -> bool:
    requested = parse_rank_player_target_command(event.get_plaintext())
    if requested is None:
        return False
    context = message_input_context(event)
    return requested.player_reference is not None or context.has_member_mentions


def _matches_command(
    parser: Callable[[str], object | None],
    event: Event,
) -> bool:
    return parser(event.get_plaintext()) is not None


def install(group: SeerMatcherGroup) -> None:
    query = group.resources.rank_queries
    admin = group.resources.rank_admin
    public_query = build_portable_rank_query_operation(
        query,
        group.player_id_resolver,
    )
    admin_operations = build_portable_rank_admin_operations(admin)
    display_limit_operation = build_portable_rank_display_operation(
        query,
        group.features,
    )
    feature_rule = seer_feature_rule(group.features, "seer_rank") & explicit_command()
    player_feature_rule = (
        seer_feature_rule(group.features, "seer_rank") & member_target_command()
    )
    priority = group.matcher_priority("seer_rank")

    list_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_list",
            help_ids=(
                "rank.global_collection",
                "rank.global_peak",
                "rank.sample_collection",
                "rank.sample_peak",
            ),
        ),
        rule=feature_rule & Rule(bind(_is_rank_list_command, query)),
        priority=priority,
    )
    list_matcher.append_handler(
        bind_async(run_portable_operation, operation=public_query)
    )

    player_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_player",
            help_ids=("rank.global_collection", "rank.global_peak"),
        ),
        rule=player_feature_rule & Rule(_is_rank_player_command),
        priority=priority,
    )
    player_matcher.append_handler(
        bind_async(run_portable_operation, operation=public_query)
    )

    score_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_score",
            help_ids=("rank.global_collection", "rank.global_peak"),
        ),
        rule=feature_rule
        & Rule(bind(_matches_command, parse_rank_score_command)),
        priority=priority,
    )
    score_matcher.append_handler(
        bind_async(run_portable_operation, operation=public_query)
    )

    cache_status = group.on_fullmatch(
        RANK_SAMPLE_STATUS_COMMANDS,
        policy=CommandPolicy.command(
            "seer_rank_cache_status",
            help_ids=("rank.sample_status",),
        ),
        rule=feature_rule,
        permission=SUPERUSER,
        priority=priority,
    )
    cache_status.append_handler(
        bind_async(
            run_portable_operation,
            operation=admin_operations["rank.sample_status"],
        )
    )

    cache_refresh = group.on_fullmatch(
        RANK_SAMPLE_REFRESH_COMMANDS,
        policy=CommandPolicy.command(
            "seer_rank_cache_refresh",
            help_ids=("rank.sample_refresh",),
        ),
        rule=feature_rule,
        permission=SUPERUSER,
        priority=priority,
    )
    cache_refresh.append_handler(
        bind_async(
            run_portable_operation,
            operation=admin_operations["rank.sample_refresh"],
        )
    )

    cache_batch = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_cache_batch",
            help_ids=("rank.page_batch",),
        ),
        rule=feature_rule
        & Rule(bind(_matches_command, parse_rank_cache_batch_command)),
        permission=SUPERUSER,
        priority=priority,
    )
    cache_batch.append_handler(
        bind_async(
            run_portable_operation,
            operation=admin_operations["rank.page_batch"],
        )
    )

    page_overview = group.on_fullmatch(
        RANK_PAGE_OVERVIEW_COMMANDS,
        policy=CommandPolicy.command(
            "seer_rank_page_cache_status",
            help_ids=("rank.page_status",),
        ),
        rule=feature_rule,
        permission=SUPERUSER,
        priority=priority,
    )
    page_overview.append_handler(
        bind_async(
            run_portable_operation,
            operation=admin_operations["rank.page_status"],
        )
    )

    page_status = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_page_cache_status",
            help_ids=("rank.page_status",),
        ),
        rule=feature_rule
        & Rule(bind(_matches_command, parse_rank_page_cache_status_command)),
        permission=SUPERUSER,
        priority=priority,
    )
    page_status.append_handler(
        bind_async(
            run_portable_operation,
            operation=admin_operations["rank.page_status"],
        )
    )

    page_refresh = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_page_cache_refresh",
            help_ids=("rank.page_refresh",),
        ),
        rule=feature_rule
        & Rule(bind(_matches_command, parse_rank_page_cache_refresh_command)),
        permission=SUPERUSER,
        priority=priority,
    )
    page_refresh.append_handler(
        bind_async(
            run_portable_operation,
            operation=admin_operations["rank.page_refresh"],
        )
    )

    display_limit = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_display_limit",
            help_ids=("rank.display_limit",),
        ),
        rule=feature_rule
        & Rule(bind(_matches_command, parse_rank_display_limit_command)),
        priority=priority,
    )
    display_limit.append_handler(
        bind_async(run_portable_operation, operation=display_limit_operation)
    )
