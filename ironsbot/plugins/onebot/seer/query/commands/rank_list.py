# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (
    MessageEvent,
)
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.core.player_reference_commands import is_player_reference_input
from ironsbot.integrations.onebot.matcher_support import bind
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.portable_queries import (
    make_portable_query_handler,
    portable_contract_rule,
)
from ironsbot.integrations.onebot.rules import explicit_command, member_target_command
from ironsbot.services.portable_player_commands import build_portable_player_operations
from ironsbot.services.portable_rank_commands import (
    build_portable_rank_admin_operations,
    build_portable_rank_operations,
)
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts
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
from .rank_list_context import (
    RANK_CACHE_BATCH_COMMAND_KEY,
    RANK_DISPLAY_LIMIT_COMMAND_KEY,
    RANK_LIST_COMMAND_KEY,
    RANK_PAGE_CACHE_REFRESH_COMMAND_KEY,
    RANK_PAGE_CACHE_STATUS_COMMAND_KEY,
    RANK_PLAYER_COMMAND_KEY,
    RANK_SCORE_COMMAND_KEY,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot.adapters.onebot.v11 import (
        MessageEvent,
    )

    from ironsbot.services.seer.rank_queries import RankQueryService


def _is_rank_list_command(
    service: RankQueryService,
    event: Event,
    state: T_State,
) -> bool:
    command = parse_rank_list_command(
        event.get_plaintext(),
        default_limit=service.default_limit(
            message_input_context(event).message.conversation
        ),
    )
    if command is None:
        return False
    state[RANK_LIST_COMMAND_KEY] = command
    return True


def _store_command(
    parser: Callable[[str], object | None],
    state_key: str,
    event: Event,
    state: T_State,
) -> bool:
    command = parser(event.get_plaintext())
    if command is None:
        return False
    state[state_key] = command
    return True


def _is_rank_player_command(
    group: SeerMatcherGroup,
    event: MessageEvent,
    state: T_State,
) -> bool:
    requested = parse_rank_player_target_command(event.get_plaintext())
    if requested is None:
        return False
    context = message_input_context(event)
    if requested.player_reference is not None and not is_player_reference_input(
        requested.player_reference,
        command_context_from_input(context),
        group.player_id_resolver.has_reference_choices,
    ):
        return False
    if requested.player_reference is None and not context.has_member_mentions:
        return False
    state[RANK_PLAYER_COMMAND_KEY] = requested
    return True


def install(group: SeerMatcherGroup) -> None:
    query = group.resources.rank_queries
    admin = group.resources.rank_admin
    player_query = build_portable_player_operations(
        group.resources.player,
        group.player_id_resolver,
        group.query_sessions,
        group.features,
        group.resources.player_detail_extensions,
        group.resources.rank_queries,
        menu_actions=group.resources.player_menu_actions,
        nickname_lookup=group.resources.player_nickname_lookup,
    )["seer.player.query"]
    operations = build_portable_rank_operations(
        query,
        group.player_id_resolver,
        group.query_sessions,
        player_query,
        group.features,
    )
    admin_operations = build_portable_rank_admin_operations(admin)
    feature_rule = seer_feature_rule(group.features, "seer_rank") & explicit_command()
    player_feature_rule = (
        seer_feature_rule(group.features, "seer_rank") & member_target_command()
    )
    priority = group.matcher_priority("seer_rank")
    admin_contract = next(
        c
        for c in rank_help_command_contracts(group.player_id_resolver)
        if c.id == "rank.sample_status"
    )
    admin_rule = feature_rule & portable_contract_rule(admin_contract, group.features)

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
        make_portable_query_handler(
            operations["rank.global_collection"], group.query_sessions
        )
    )

    player_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_player",
            help_ids=("rank.global_collection", "rank.global_peak"),
            semantic_request=lambda _event, _state: None,
        ),
        rule=player_feature_rule & Rule(bind(_is_rank_player_command, group)),
        priority=priority,
    )
    player_matcher.append_handler(
        make_portable_query_handler(
            operations["rank.global_collection"], group.query_sessions
        )
    )

    score_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_score",
            help_ids=("rank.global_collection", "rank.global_peak"),
        ),
        rule=feature_rule
        & Rule(
            bind(
                _store_command,
                parse_rank_score_command,
                RANK_SCORE_COMMAND_KEY,
            )
        ),
        priority=priority,
    )
    score_matcher.append_handler(
        make_portable_query_handler(
            operations["rank.global_collection"], group.query_sessions
        )
    )

    cache_status = group.on_fullmatch(
        RANK_SAMPLE_STATUS_COMMANDS,
        policy=CommandPolicy.command(
            "seer_rank_cache_status",
            help_ids=("rank.sample_status",),
        ),
        rule=admin_rule,
        priority=priority,
    )
    cache_status.append_handler(
        make_portable_query_handler(
            admin_operations["rank.sample_status"], group.query_sessions
        )
    )

    cache_refresh = group.on_fullmatch(
        RANK_SAMPLE_REFRESH_COMMANDS,
        policy=CommandPolicy.command(
            "seer_rank_cache_refresh",
            help_ids=("rank.sample_refresh",),
        ),
        rule=admin_rule,
        priority=priority,
    )
    cache_refresh.append_handler(
        make_portable_query_handler(
            admin_operations["rank.sample_refresh"], group.query_sessions
        )
    )

    cache_batch = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_cache_batch",
            help_ids=("rank.page_batch",),
        ),
        rule=admin_rule
        & Rule(
            bind(
                _store_command,
                parse_rank_cache_batch_command,
                RANK_CACHE_BATCH_COMMAND_KEY,
            )
        ),
        priority=priority,
    )
    cache_batch.append_handler(
        make_portable_query_handler(
            admin_operations["rank.page_batch"], group.query_sessions
        )
    )

    page_overview = group.on_fullmatch(
        RANK_PAGE_OVERVIEW_COMMANDS,
        policy=CommandPolicy.command(
            "seer_rank_page_cache_status",
            help_ids=("rank.page_status",),
        ),
        rule=admin_rule,
        priority=priority,
    )
    page_overview.append_handler(
        make_portable_query_handler(
            admin_operations["rank.page_status"], group.query_sessions
        )
    )

    page_status = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_page_cache_status",
            help_ids=("rank.page_status",),
        ),
        rule=admin_rule
        & Rule(
            bind(
                _store_command,
                parse_rank_page_cache_status_command,
                RANK_PAGE_CACHE_STATUS_COMMAND_KEY,
            )
        ),
        priority=priority,
    )
    page_status.append_handler(
        make_portable_query_handler(
            admin_operations["rank.page_status"], group.query_sessions
        )
    )

    page_refresh = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_page_cache_refresh",
            help_ids=("rank.page_refresh",),
        ),
        rule=admin_rule
        & Rule(
            bind(
                _store_command,
                parse_rank_page_cache_refresh_command,
                RANK_PAGE_CACHE_REFRESH_COMMAND_KEY,
            )
        ),
        priority=priority,
    )
    page_refresh.append_handler(
        make_portable_query_handler(
            admin_operations["rank.page_refresh"], group.query_sessions
        )
    )

    display_limit = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_display_limit",
            help_ids=("rank.display_limit",),
        ),
        rule=feature_rule
        & Rule(
            bind(
                _store_command,
                parse_rank_display_limit_command,
                RANK_DISPLAY_LIMIT_COMMAND_KEY,
            )
        ),
        priority=priority,
    )
    display_limit.append_handler(
        make_portable_query_handler(
            operations["rank.display_limit"], group.query_sessions
        )
    )
