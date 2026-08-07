# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
)
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.runtime.matchers import CommandPolicy, bind, bind_async
from ironsbot.runtime.permissions import can_manage_group_event
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import explicit_command
from ironsbot.services.seer.external_references import (
    SeerInfoReference,
    SeerInfoReferences,
    peak_rank_reference,
)
from ironsbot.services.seer.rank_display import parse_rank_display_limit_command
from ironsbot.services.seer.rank_list_parsing import (
    parse_rank_cache_batch_command,
    parse_rank_list_command,
    parse_rank_page_cache_refresh_command,
    parse_rank_page_cache_status_command,
    parse_rank_player_command,
    parse_rank_score_command,
    with_admin_prefix,
)

from ..group import SeerMatcherGroup, seer_feature_rule
from .player_target import resolve_event_player_reference
from .rank_list_context import (
    RANK_CACHE_BATCH_COMMAND_KEY,
    RANK_DISPLAY_LIMIT_COMMAND_KEY,
    RANK_LIST_COMMAND_KEY,
    RANK_PAGE_CACHE_REFRESH_COMMAND_KEY,
    RANK_PAGE_CACHE_STATUS_COMMAND_KEY,
    RANK_PLAYER_COMMAND_KEY,
    RANK_SCORE_COMMAND_KEY,
    event_group_id,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.features import FeatureService
    from ironsbot.services.seer.rank_admin import RankAdminService
    from ironsbot.services.seer.rank_queries import RankQueryService


def _rank_reference(command: object) -> SeerInfoReference | None:
    kind = getattr(command, "kind", "global")
    if kind != "global":
        return None
    rank_key = str(getattr(command, "rank_key", ""))
    peak_type = {
        "竞技段位": 1,
        "狂野段位": 2,
        "专家段位": 3,
    }.get(rank_key)
    if peak_type is None:
        return None
    return peak_rank_reference(peak_type=peak_type, category="player")


def _is_rank_list_command(
    service: RankQueryService,
    event: Event,
    state: T_State,
) -> bool:
    command = parse_rank_list_command(
        event.get_plaintext(),
        default_limit=service.default_limit(event_group_id(event)),
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
    event: Event,
    state: T_State,
) -> bool:
    return _store_command(
        partial(
            parse_rank_player_command,
            resolve_player_id=partial(
                resolve_event_player_reference,
                group.player_accounts,
                event,
            ),
        ),
        RANK_PLAYER_COMMAND_KEY,
        event,
        state,
    )


async def _handle_list(
    service: RankQueryService,
    references: SeerInfoReferences,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    command = state[RANK_LIST_COMMAND_KEY]
    reply = await service.list_reply(
        command,
        qq_user_id=event.user_id,
        group_id=event_group_id(event),
    )
    try:
        await finish_event_reply(
            matcher,
            event,
            references.append(
                reply.text,
                _rank_reference(command) if reply.query_work is not None else None,
            ),
        )
    except FinishedException:
        service.record_returned_general_reply(
            qq_user_id=event.user_id,
            action_key=f"rank:list:{command.rank_key}",
            reply=reply,
        )
        raise
    else:
        service.record_returned_general_reply(
            qq_user_id=event.user_id,
            action_key=f"rank:list:{command.rank_key}",
            reply=reply,
        )


async def _handle_score(
    service: RankQueryService,
    references: SeerInfoReferences,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    command = state[RANK_SCORE_COMMAND_KEY]
    reply = await service.score_reply(
        command,
        group_id=event_group_id(event),
        qq_user_id=event.user_id,
    )
    try:
        await finish_event_reply(
            matcher,
            event,
            references.append(
                reply.text,
                _rank_reference(command) if reply.query_work is not None else None,
            ),
        )
    except FinishedException:
        service.record_returned_general_reply(
            qq_user_id=event.user_id,
            action_key=f"rank:score:{command.rank_key}",
            reply=reply,
        )
        raise
    else:
        service.record_returned_general_reply(
            qq_user_id=event.user_id,
            action_key=f"rank:score:{command.rank_key}",
            reply=reply,
        )


async def _handle_player(
    service: RankQueryService,
    references: SeerInfoReferences,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    command = state[RANK_PLAYER_COMMAND_KEY]
    reply = await service.player_reply(
        command,
        qq_user_id=event.user_id,
        group_id=event_group_id(event),
    )
    try:
        await finish_event_reply(
            matcher,
            event,
            references.append(
                reply.text,
                _rank_reference(command) if reply.query_work is not None else None,
            ),
        )
    except FinishedException:
        service.record_returned_player(command, event.user_id, reply)
        raise
    else:
        service.record_returned_player(command, event.user_id, reply)


async def _progress(
    matcher: Matcher,
    event: MessageEvent,
    message: str,
) -> None:
    await send_event_reply(matcher, event, message)


async def _handle_cache_batch(
    service: RankAdminService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    message = await service.cache_batch(
        state[RANK_CACHE_BATCH_COMMAND_KEY],
        user_id=int(event.user_id),
        progress=partial(_progress, matcher, event),
    )
    await finish_event_reply(matcher, event, message)


async def _handle_page_status(
    service: RankAdminService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await finish_event_reply(
        matcher,
        event,
        service.page_status(state[RANK_PAGE_CACHE_STATUS_COMMAND_KEY]),
    )


async def _handle_page_overview(
    service: RankAdminService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(matcher, event, service.page_overview())


async def _handle_page_refresh(
    service: RankAdminService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    message = await service.page_refresh(
        state[RANK_PAGE_CACHE_REFRESH_COMMAND_KEY],
        user_id=int(event.user_id),
        progress=partial(_progress, matcher, event),
    )
    await finish_event_reply(matcher, event, message)


async def _handle_cache_status(
    service: RankAdminService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(
        matcher,
        event,
        service.cache_status(event_group_id(event)),
    )


async def _handle_cache_refresh(
    service: RankAdminService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    message = await service.cache_refresh(
        user_id=int(event.user_id),
        progress=partial(_progress, matcher, event),
    )
    await finish_event_reply(matcher, event, message)


async def _handle_display_limit(
    service: RankQueryService,
    features: FeatureService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    group_id = event_group_id(event)
    message = service.set_display_limit(
        group_id=group_id,
        user_id=int(event.user_id),
        can_manage=(
            isinstance(event, GroupMessageEvent)
            and can_manage_group_event(features, event)
        ),
        limit=int(state[RANK_DISPLAY_LIMIT_COMMAND_KEY]),
    )
    await finish_event_reply(matcher, event, message)


def install(group: SeerMatcherGroup) -> None:
    query = group.resources.rank_queries
    references = group.resources.external_references
    admin = group.resources.rank_admin
    feature_rule = seer_feature_rule(group.features, "seer_rank") & explicit_command()
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
        rule=feature_rule
        & Rule(bind(_is_rank_list_command, query)),
        priority=priority,
    )
    list_matcher.append_handler(bind_async(_handle_list, query, references))

    player_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_player",
            help_ids=("rank.global_collection", "rank.global_peak"),
        ),
        rule=feature_rule
        & Rule(bind(_is_rank_player_command, group)),
        priority=priority,
    )
    player_matcher.append_handler(bind_async(_handle_player, query, references))

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
    score_matcher.append_handler(bind_async(_handle_score, query, references))

    cache_status = group.on_fullmatch(
        with_admin_prefix(("样本情况", "样本状态")),
        policy=CommandPolicy.command(
            "seer_rank_cache_status",
            help_ids=("rank.sample_status",),
        ),
        rule=feature_rule,
        permission=SUPERUSER,
        priority=priority,
    )
    cache_status.append_handler(bind_async(_handle_cache_status, admin))

    cache_refresh = group.on_fullmatch(
        with_admin_prefix(("刷新样本",)),
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
            _handle_cache_refresh,
            admin,
        )
    )

    cache_batch = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_cache_batch",
            help_ids=("rank.page_batch",),
        ),
        rule=feature_rule
        & Rule(
            bind(
                _store_command,
                parse_rank_cache_batch_command,
                RANK_CACHE_BATCH_COMMAND_KEY,
            )
        ),
        permission=SUPERUSER,
        priority=priority,
    )
    cache_batch.append_handler(
        bind_async(_handle_cache_batch, admin)
    )

    page_overview = group.on_fullmatch(
        with_admin_prefix(("榜单情况", "榜单状态")),
        policy=CommandPolicy.command(
            "seer_rank_page_cache_status",
            help_ids=("rank.page_status",),
        ),
        rule=feature_rule,
        permission=SUPERUSER,
        priority=priority,
    )
    page_overview.append_handler(bind_async(_handle_page_overview, admin))

    page_status = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_page_cache_status",
            help_ids=("rank.page_status",),
        ),
        rule=feature_rule
        & Rule(
            bind(
                _store_command,
                parse_rank_page_cache_status_command,
                RANK_PAGE_CACHE_STATUS_COMMAND_KEY,
            )
        ),
        permission=SUPERUSER,
        priority=priority,
    )
    page_status.append_handler(bind_async(_handle_page_status, admin))

    page_refresh = group.on_message(
        policy=CommandPolicy.command(
            "seer_rank_page_cache_refresh",
            help_ids=("rank.page_refresh",),
        ),
        rule=feature_rule
        & Rule(
            bind(
                _store_command,
                parse_rank_page_cache_refresh_command,
                RANK_PAGE_CACHE_REFRESH_COMMAND_KEY,
            )
        ),
        permission=SUPERUSER,
        priority=priority,
    )
    page_refresh.append_handler(
        bind_async(_handle_page_refresh, admin)
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
        bind_async(_handle_display_limit, query, group.features)
    )
