# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (
    MessageEvent,  # noqa: TC002 - NoneBot resolves it at runtime
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule

from ironsbot.runtime.feature_policy import event_is_feature_allowed
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import no_reply
from ironsbot.services.activity.commands import (
    is_current_seer_activity_text,
    is_soon_ending_seer_activity_text,
)

if TYPE_CHECKING:
    from ironsbot.core.features import FeatureService
    from ironsbot.services.activity.service import ActivityService


async def _is_current_seer_activity_command(event: Event) -> bool:
    return is_current_seer_activity_text(event.get_plaintext())


async def _is_soon_ending_seer_activity_command(event: Event) -> bool:
    return is_soon_ending_seer_activity_text(event.get_plaintext())


def install(
    registry: MatcherRegistry,
    service: ActivityService,
    features: FeatureService,
) -> None:
    async def handle_current(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        await finish_event_reply(
            matcher,
            event,
            await service.build_current_message(),
        )

    async def handle_soon_ending(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        await finish_event_reply(
            matcher,
            event,
            await service.build_current_message(soon_only=True),
        )

    current_matcher = registry.on_message(
        policy=CommandPolicy.command("seer_activity_current"),
        rule=Rule(_is_current_seer_activity_command) & no_reply(),
        permission=SUPERUSER,
        priority=registry.priority("activity"),
        block=True,
    )
    current_matcher.append_handler(handle_current)

    ending_matcher = registry.on_message(
        policy=CommandPolicy.command("seer_activity_ending"),
        rule=(
            Rule(
                lambda event: event_is_feature_allowed(
                    features, event, "seer_activity_query"
                )
            )
            & Rule(_is_soon_ending_seer_activity_command)
            & no_reply()
        ),
        priority=registry.priority("activity"),
        block=True,
    )
    ending_matcher.append_handler(handle_soon_ending)
