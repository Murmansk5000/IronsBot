# SPDX-License-Identifier: GPL-3.0-or-later
"""Peak query matchers."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Literal

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot_plugin_saa import Image, MessageFactory

from ironsbot.runtime.matchers import CommandPolicy, bind_async
from ironsbot.runtime.rules import no_reply
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from ironsbot.services.seer.peak import (
        PeakQueryResult,
        PeakQueryService,
    )


async def _report_progress(matcher: Matcher, message: str) -> None:
    await matcher.send(message)


async def _finish_result(
    result: PeakQueryResult,
    matcher: Matcher,
) -> None:
    if result.message:
        await matcher.finish(result.message)
        return
    if result.text:
        await matcher.finish(result.text)
        return
    if result.image is not None:
        await MessageFactory(Image(result.image)).finish(at_sender=False)


async def _handle_pool(
    service: PeakQueryService,
    matcher: Matcher,
    *,
    expert: bool,
) -> None:
    try:
        result = await service.pool(
            expert=expert,
            progress=partial(_report_progress, matcher),
        )
    except DataUnavailableError:
        await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
        return
    await _finish_result(result, matcher)


async def _handle_vote(
    service: PeakQueryService,
    matcher: Matcher,
) -> None:
    try:
        result = await service.vote(partial(_report_progress, matcher))
    except DataUnavailableError:
        await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
        return
    await _finish_result(result, matcher)


async def _handle_item_rank(
    service: PeakQueryService,
    matcher: Matcher,
    event: Event,
    *,
    kind: Literal["套装", "称号"],
) -> None:
    try:
        result = await service.item_rank(
            event.get_plaintext(),
            kind=kind,
        )
    except DataUnavailableError:
        await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
        return
    await _finish_result(result, matcher)


async def _handle_pet_rank(
    service: PeakQueryService,
    matcher: Matcher,
    event: Event,
) -> None:
    try:
        result = await service.pet_rank(
            event.get_plaintext(),
            partial(_report_progress, matcher),
        )
    except DataUnavailableError:
        await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
        return
    await _finish_result(result, matcher)


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.peak_query
    rule = seer_feature_rule(group.features, "seer_peak") & no_reply()
    priority = group.matcher_priority("seer_peak")

    pool = group.on_fullmatch(
        ("竞技池", "巅峰竞技池", "竞技精灵池", "限制池"),
        policy=CommandPolicy.command("seer_peak_pool"),
        rule=rule,
        priority=priority,
    )
    pool.append_handler(bind_async(_handle_pool, service, expert=False))

    expert_pool = group.on_fullmatch(
        ("专家池", "巅峰专家池", "专家禁用池"),
        policy=CommandPolicy.command("seer_peak_expert_pool"),
        rule=rule,
        priority=priority,
    )
    expert_pool.append_handler(bind_async(_handle_pool, service, expert=True))

    vote = group.on_fullmatch(
        ("巅峰投票", "巅峰票选", "巅峰池票选", "竞技池票选", "限制池票选"),
        policy=CommandPolicy.command("seer_peak_vote"),
        rule=rule,
        priority=priority,
    )
    vote.append_handler(bind_async(_handle_vote, service))

    suit = group.on_fullmatch(
        ("竞技套装榜", "狂野套装榜", "专家套装榜"),
        policy=CommandPolicy.command("seer_peak_suit_rank"),
        rule=rule,
        priority=priority,
    )
    suit.append_handler(
        bind_async(_handle_item_rank, service, kind="套装")
    )

    title = group.on_fullmatch(
        ("竞技称号榜", "狂野称号榜", "专家称号榜"),
        policy=CommandPolicy.command("seer_peak_title_rank"),
        rule=rule,
        priority=priority,
    )
    title.append_handler(
        bind_async(_handle_item_rank, service, kind="称号")
    )

    pet = group.on_fullmatch(
        (
            "竞技精灵月榜",
            "狂野精灵月榜",
            "专家精灵月榜",
            "竞技精灵总榜",
            "狂野精灵总榜",
            "专家精灵总榜",
        ),
        policy=CommandPolicy.command("seer_peak_pet_rank"),
        rule=rule,
        priority=priority,
    )
    pet.append_handler(bind_async(_handle_pet_rank, service))
