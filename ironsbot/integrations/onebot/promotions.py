# SPDX-License-Identifier: MIT
"""OneBot rendering for configuration-backed promotion attachments."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.runtime.onebot_identity import onebot_actor_ref

if TYPE_CHECKING:
    from ironsbot.core.messaging import MessageTarget
    from ironsbot.core.platform import ActorRef
    from ironsbot.core.promotions import PromotionCatalog, PromotionConfig


class OneBotTargetFeaturePolicy(Protocol):
    """Feature checks adapted from a legacy OneBot target at the edge."""

    def conversation_has_feature(
        self,
        conversation: ConversationRef,
        feature: str,
    ) -> bool: ...

    def actor_has_feature(self, actor: ActorRef, feature: str) -> bool: ...


def promotion_enabled_for_target(
    features: OneBotTargetFeaturePolicy,
    target: MessageTarget,
    promotion: PromotionConfig,
) -> bool:
    """Whether this OneBot target has opted into one promotion feature."""

    if not promotion.enabled:
        return False
    if target.target_type == "group":
        return features.conversation_has_feature(
            _onebot_target_conversation(target),
            promotion.feature,
        )
    return features.actor_has_feature(
        onebot_actor_ref(target.target_id),
        promotion.feature,
    )


def append_promotions_for_target(
    features: OneBotTargetFeaturePolicy,
    catalog: PromotionCatalog,
    message: str | Message,
    target: MessageTarget,
) -> str | Message:
    """Append every configured push promotion allowed for this OneBot target."""

    result = message
    for promotion in catalog.push_promotions:
        if promotion_enabled_for_target(features, target, promotion):
            result = _append_promotion(result, promotion)
    return result


def _append_promotion(
    message: str | Message,
    promotion: PromotionConfig,
) -> str | Message:
    body = promotion.message
    if _message_already_contains(message, promotion):
        return message
    if isinstance(message, Message):
        return Message(message) + MessageSegment.text(f"\n\n{body}")

    text = message.rstrip()
    return body if not text else f"{text}\n\n{body}"


def _message_already_contains(
    message: str | Message,
    promotion: PromotionConfig,
) -> bool:
    rendered = str(message)
    return promotion.message in rendered or (
        bool(promotion.url) and promotion.url in rendered
    )


def _onebot_target_conversation(target: MessageTarget) -> ConversationRef:
    return ConversationRef(
        Platform.ONEBOT,
        target.target_type,
        str(target.target_id),
    )
