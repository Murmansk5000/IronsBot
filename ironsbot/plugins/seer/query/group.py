# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot import MatcherGroup
from nonebot.adapters import Event
from nonebot.rule import Rule

from ironsbot.shared.features import is_event_feature_allowed
from ironsbot.shared.matcher_priority import get_matcher_priority


def seer_feature_rule(feature: str) -> Rule:
    async def _is_feature_allowed(event: Event) -> bool:
        return is_event_feature_allowed(event, feature)

    return Rule(_is_feature_allowed)


def seer_feature_priority(feature: str, fallback: int | None = None) -> int:
    if fallback is None:
        fallback = get_matcher_priority("seer_query", 90)
    return get_matcher_priority(feature, fallback)


matcher_group = MatcherGroup(
    block=True,
    priority=get_matcher_priority("seer_query", 2),
)
