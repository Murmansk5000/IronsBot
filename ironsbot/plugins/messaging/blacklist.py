# SPDX-License-Identifier: MIT
"""Highest-priority silent block for configured conversation sources."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind

if TYPE_CHECKING:
    from ironsbot.core.features import FeatureService


BLACKLIST_PRIORITY = -40


def event_is_blacklisted(
    features: FeatureService,
    event: MessageEvent,
) -> bool:
    return features.is_conversation_blocked(
        event.user_id,
        event.group_id if isinstance(event, GroupMessageEvent) else None,
    )


def install(
    registry: MatcherRegistry,
    features: FeatureService,
) -> None:
    async def discard(_matcher: Matcher) -> None:
        raise FinishedException

    matcher = registry.on_message(
        policy=CommandPolicy.exempt("conversation blacklist"),
        rule=Rule(bind(event_is_blacklisted, features)),
        priority=BLACKLIST_PRIORITY,
        block=True,
    )
    matcher.append_handler(discard)
