from __future__ import annotations

from ironsbot.config.models.features import FeatureConfig
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.services.messaging.proactive_delivery import (
    append_push_promotions,
)
from tests.helpers.promotions import FIRE_MANUAL_PROMOTION, FIRE_MANUAL_PROMOTIONS
from tests.helpers.runtime import build_test_runtime


def _message_text(message: OutboundMessage) -> str:
    return "".join(part.text for part in message.parts if isinstance(part, TextPart))


def _with_promotions(
    features: object,
    conversation: ConversationRef,
) -> OutboundMessage:
    return append_push_promotions(
        OutboundMessage((TextPart("正文"),)),
        conversation=conversation,
        features=features,  # type: ignore[arg-type]
        promotions=FIRE_MANUAL_PROMOTIONS,
    )


def test_fire_manual_push_attachment_is_independent_from_ai_intents() -> None:
    ai_only = build_test_runtime(
        feature_config=FeatureConfig(
            group_policy={
                "1001": ["ai_intent", "ai_intent_fire_manual"],
            },
            user_policy={
                "2001": ["ai_intent", "ai_intent_fire_manual"],
            },
        )
    ).features
    explicit_ad = build_test_runtime(
        feature_config=FeatureConfig(
            group_policy={"1001": ["fire_manual_ad"]},
            user_policy={"2001": ["fire_manual_ad"]},
        )
    ).features

    assert FIRE_MANUAL_PROMOTION.message not in _message_text(
        _with_promotions(
            ai_only,
            ConversationRef(Platform.ONEBOT, "group", "1001"),
        )
    )
    assert FIRE_MANUAL_PROMOTION.message not in _message_text(
        _with_promotions(
            ai_only,
            ConversationRef(Platform.ONEBOT, "private", "2001"),
        )
    )
    assert FIRE_MANUAL_PROMOTION.message in _message_text(
        _with_promotions(
            explicit_ad,
            ConversationRef(Platform.ONEBOT, "group", "1001"),
        )
    )
    assert FIRE_MANUAL_PROMOTION.message in _message_text(
        _with_promotions(
            explicit_ad,
            ConversationRef(Platform.ONEBOT, "private", "2001"),
        )
    )


def test_fire_manual_push_attachment_respects_all_bundle_and_not_superuser_bypass() -> (
    None
):
    features = build_test_runtime(
        feature_config=FeatureConfig(user_policy={"2001": ["all"]}),
        superuser_ids=(1002,),
    ).features

    assert FIRE_MANUAL_PROMOTION.message in _message_text(
        _with_promotions(
            features,
            ConversationRef(Platform.ONEBOT, "private", "2001"),
        )
    )
    assert FIRE_MANUAL_PROMOTION.message not in _message_text(
        _with_promotions(
            features,
            ConversationRef(Platform.ONEBOT, "private", "1002"),
        )
    )
