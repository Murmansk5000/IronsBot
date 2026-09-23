# SPDX-License-Identifier: GPL-3.0-or-later
"""Peak query matchers."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Literal

from nonebot.adapters.onebot.v11 import MessageEvent  # noqa: TC002
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.integrations.onebot.matchers import CommandPolicy, bind_async
from ironsbot.integrations.onebot.message_rendering import (
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.replies import finish_event_reply, send_event_reply
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
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

if TYPE_CHECKING:
    from ironsbot.services.seer.peak import (
        PeakQueryResult,
        PeakQueryService,
    )


async def _report_progress(matcher: Matcher, event: MessageEvent, message: str) -> None:
    await send_event_reply(matcher, event, message)


async def _finish_result(
    result: PeakQueryResult,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(
        matcher, event, render_onebot_outbound_message(result.to_outbound())
    )


async def _handle_pool(
    service: PeakQueryService,
    matcher: Matcher,
    event: MessageEvent,
    *,
    expert: bool,
) -> None:
    try:
        result = await service.pool(
            expert=expert,
            progress=partial(_report_progress, matcher, event),
        )
    except DataUnavailableError:
        await finish_event_reply(matcher, event, DATABASE_UNAVAILABLE_MESSAGE)
        return
    await _finish_result(result, matcher, event)


async def _handle_vote(
    service: PeakQueryService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    try:
        result = await service.vote(partial(_report_progress, matcher, event))
    except DataUnavailableError:
        await finish_event_reply(matcher, event, DATABASE_UNAVAILABLE_MESSAGE)
        return
    await _finish_result(result, matcher, event)


async def _handle_master_pool(
    service: PeakQueryService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    try:
        result = await service.master_pool(partial(_report_progress, matcher, event))
    except DataUnavailableError:
        await finish_event_reply(matcher, event, DATABASE_UNAVAILABLE_MESSAGE)
        return
    await _finish_result(result, matcher, event)


async def _handle_item_rank(
    service: PeakQueryService,
    matcher: Matcher,
    event: MessageEvent,
    *,
    kind: Literal["套装", "称号"],
) -> None:
    try:
        result = await service.item_rank(
            event.get_plaintext(),
            kind=kind,
        )
    except DataUnavailableError:
        await finish_event_reply(matcher, event, DATABASE_UNAVAILABLE_MESSAGE)
        return
    await _finish_result(result, matcher, event)


async def _handle_pet_rank(
    service: PeakQueryService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    try:
        result = await service.pet_rank(
            event.get_plaintext(),
            partial(_report_progress, matcher, event),
        )
    except DataUnavailableError:
        await finish_event_reply(matcher, event, DATABASE_UNAVAILABLE_MESSAGE)
        return
    await _finish_result(result, matcher, event)


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.peak_query
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
    pool.append_handler(bind_async(_handle_pool, service, expert=False))

    expert_pool = group.on_fullmatch(
        PEAK_EXPERT_POOL_COMMANDS,
        policy=CommandPolicy.command(
            "seer_peak_expert_pool",
            help_ids=("seer.peak.query",),
        ),
        rule=rule,
        priority=priority,
    )
    expert_pool.append_handler(bind_async(_handle_pool, service, expert=True))

    master_pool = group.on_fullmatch(
        PEAK_MASTER_POOL_COMMANDS,
        policy=CommandPolicy.command(
            "seer_peak_master_pool",
            help_ids=("seer.peak.query",),
        ),
        rule=rule,
        priority=priority,
    )
    master_pool.append_handler(bind_async(_handle_master_pool, service))

    vote = group.on_fullmatch(
        PEAK_VOTE_COMMANDS,
        policy=CommandPolicy.command(
            "seer_peak_vote",
            help_ids=("seer.peak.query",),
        ),
        rule=rule,
        priority=priority,
    )
    vote.append_handler(bind_async(_handle_vote, service))

    suit = group.on_fullmatch(
        PEAK_SUIT_RANK_COMMANDS,
        policy=CommandPolicy.command(
            "seer_peak_suit_rank",
            help_ids=("seer.peak.rank",),
        ),
        rule=rule,
        priority=priority,
    )
    suit.append_handler(bind_async(_handle_item_rank, service, kind="套装"))

    title = group.on_fullmatch(
        PEAK_TITLE_RANK_COMMANDS,
        policy=CommandPolicy.command(
            "seer_peak_title_rank",
            help_ids=("seer.peak.rank",),
        ),
        rule=rule,
        priority=priority,
    )
    title.append_handler(bind_async(_handle_item_rank, service, kind="称号"))

    pet = group.on_fullmatch(
        PEAK_PET_RANK_COMMANDS,
        policy=CommandPolicy.command(
            "seer_peak_pet_rank",
            help_ids=("seer.peak.rank",),
        ),
        rule=rule,
        priority=priority,
    )
    pet.append_handler(bind_async(_handle_pet_rank, service))
