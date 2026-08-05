from __future__ import annotations

from ironsbot.config.models.features import FeatureConfig
from ironsbot.integrations.onebot.promotions import (
    promotion_enabled_for_target,
)
from ironsbot.integrations.onebot.targets import OneBotMessageTarget
from tests.helpers.promotions import FIRE_MANUAL_PROMOTION
from tests.helpers.runtime import build_test_runtime


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

    assert not promotion_enabled_for_target(
        ai_only,
        OneBotMessageTarget("group", 1001),
        FIRE_MANUAL_PROMOTION,
    )
    assert not promotion_enabled_for_target(
        ai_only,
        OneBotMessageTarget("private", 2001),
        FIRE_MANUAL_PROMOTION,
    )
    assert promotion_enabled_for_target(
        explicit_ad,
        OneBotMessageTarget("group", 1001),
        FIRE_MANUAL_PROMOTION,
    )
    assert promotion_enabled_for_target(
        explicit_ad,
        OneBotMessageTarget("private", 2001),
        FIRE_MANUAL_PROMOTION,
    )


def test_fire_manual_push_attachment_respects_all_bundle_and_not_superuser_bypass() -> (
    None
):
    features = build_test_runtime(
        feature_config=FeatureConfig(user_policy={"2001": ["all"]}),
        superuser_ids=(1002,),
    ).features

    assert promotion_enabled_for_target(
        features,
        OneBotMessageTarget("private", 2001),
        FIRE_MANUAL_PROMOTION,
    )
    assert not promotion_enabled_for_target(
        features,
        OneBotMessageTarget("private", 1002),
        FIRE_MANUAL_PROMOTION,
    )
