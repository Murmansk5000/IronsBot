# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from nonebot.rule import Rule

if TYPE_CHECKING:
    from nonebot.adapters import Event


class FeaturePolicy(Protocol):
    def group_has_feature(self, group_id: int, feature: str) -> bool: ...

    def is_group_feature_allowed(
        self,
        user_id: int,
        group_id: int,
        feature: str,
    ) -> bool: ...

    def is_private_feature_allowed(self, user_id: int, feature: str) -> bool: ...


def event_has_feature(
    features: FeaturePolicy,
    event: Event,
    feature: str,
) -> bool:
    if isinstance(event, GroupMessageEvent):
        return features.group_has_feature(event.group_id, feature)
    if isinstance(event, PrivateMessageEvent):
        return features.is_private_feature_allowed(event.user_id, feature)
    return False


def event_is_feature_allowed(
    features: FeaturePolicy,
    event: Event,
    feature: str,
) -> bool:
    if isinstance(event, GroupMessageEvent):
        return features.is_group_feature_allowed(
            event.user_id,
            event.group_id,
            feature,
        )
    if isinstance(event, PrivateMessageEvent):
        return features.is_private_feature_allowed(event.user_id, feature)
    return False


def feature_rule(features: FeaturePolicy, feature: str) -> Rule:
    """Create a generic event rule for a feature-policy key."""

    async def _is_feature_allowed(event: Event) -> bool:
        return event_has_feature(features, event, feature)

    return Rule(_is_feature_allowed)
