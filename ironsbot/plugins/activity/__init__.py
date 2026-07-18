# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nonebot.permission import SUPERUSER
from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.services.activity.commands import (
    is_current_seer_activity_text,
    is_soon_ending_seer_activity_text,
)
from ironsbot.shared.features import is_event_feature_allowed
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import finish_event_reply
from ironsbot.utils.rule import no_reply

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher

    from ironsbot.services.activity.service import ActivityService


async def _is_current_seer_activity_command(event: Event) -> bool:
    return is_current_seer_activity_text(event.get_plaintext())


async def _is_soon_ending_seer_activity_command(event: Event) -> bool:
    return is_soon_ending_seer_activity_text(event.get_plaintext())


def install(
    registry: MatcherRegistry,
    service: ActivityService,
) -> None:
    async def handle_current(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        await finish_event_reply(
            matcher,
            event,
            await asyncio.to_thread(service.build_current_message),
        )

    async def handle_soon_ending(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        await finish_event_reply(
            matcher,
            event,
            await asyncio.to_thread(
                service.build_current_message,
                soon_only=True,
            ),
        )

    current_matcher = registry.on_message(
        policy=CommandPolicy.command("seer_activity_current"),
        rule=Rule(_is_current_seer_activity_command) & no_reply(),
        permission=SUPERUSER,
        priority=get_matcher_priority("activity", 5),
        block=True,
    )
    current_matcher.append_handler(handle_current)

    ending_matcher = registry.on_message(
        policy=CommandPolicy.command("seer_activity_ending"),
        rule=(
            Rule(lambda event: is_event_feature_allowed(event, "seer_activity_query"))
            & Rule(_is_soon_ending_seer_activity_command)
            & no_reply()
        ),
        priority=get_matcher_priority("activity", 5),
        block=True,
    )
    ending_matcher.append_handler(handle_soon_ending)
