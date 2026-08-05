# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from nonebot.rule import Rule

from ironsbot.integrations.onebot.message_input import message_input_context

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.core.platform import ActorRef, ConversationRef


class FeaturePolicy(Protocol):
    def conversation_has_feature(
        self,
        conversation: ConversationRef,
        feature: str,
    ) -> bool: ...

    def is_feature_allowed(
        self,
        actor: ActorRef,
        conversation: ConversationRef,
        feature: str,
    ) -> bool: ...


def event_is_feature_allowed(
    features: FeaturePolicy,
    event: Event,
    feature: str,
) -> bool:
    if not isinstance(event, GroupMessageEvent | PrivateMessageEvent):
        return False
    message = message_input_context(event).message
    return features.is_feature_allowed(message.actor, message.conversation, feature)


def event_is_feature_visible_in_help(
    features: FeaturePolicy,
    event: Event,
    feature: str,
) -> bool:
    """Check help visibility without letting a superuser bypass a group policy.

    A superuser may execute a feature in any group, but the help menu should
    describe what that group has explicitly enabled for its members.
    """

    if isinstance(event, GroupMessageEvent):
        return features.conversation_has_feature(
            message_input_context(event).message.conversation,
            feature,
        )
    return event_is_feature_allowed(features, event, feature)


def feature_rule(features: FeaturePolicy, feature: str) -> Rule:
    """Create a generic event rule for a feature-policy key."""

    async def _is_feature_allowed(event: Event) -> bool:
        return event_is_feature_allowed(features, event, feature)

    return Rule(_is_feature_allowed)
