from __future__ import annotations

from ironsbot.core.features import FeatureConfig
from ironsbot.core.messaging import MessageTarget
from ironsbot.services.messaging.promotions import (
    fire_manual_ad_enabled_for_target,
)
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

    assert not fire_manual_ad_enabled_for_target(
        ai_only,
        MessageTarget("group", 1001),
    )
    assert not fire_manual_ad_enabled_for_target(
        ai_only,
        MessageTarget("private", 2001),
    )
    assert fire_manual_ad_enabled_for_target(
        explicit_ad,
        MessageTarget("group", 1001),
    )
    assert fire_manual_ad_enabled_for_target(
        explicit_ad,
        MessageTarget("private", 2001),
    )


def test_fire_manual_push_attachment_respects_all_bundle_and_not_superuser_bypass(
) -> None:
    features = build_test_runtime(
        feature_config=FeatureConfig(user_policy={"2001": ["all"]}),
        superuser_ids=(1002,),
    ).features

    assert fire_manual_ad_enabled_for_target(
        features,
        MessageTarget("private", 2001),
    )
    assert not fire_manual_ad_enabled_for_target(
        features,
        MessageTarget("private", 1002),
    )
