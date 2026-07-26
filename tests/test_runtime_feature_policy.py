# SPDX-License-Identifier: MIT
from ironsbot.core.features import FeatureConfig, FeatureService
from ironsbot.runtime.feature_policy import event_is_feature_allowed
from tests.helpers.onebot_events import group_message_event

_SUPERUSER_ID = 10001


def test_group_event_feature_policy_uses_superuser_bypass() -> None:
    features = FeatureService(
        FeatureConfig(superuser_bypass=True),
        frozenset({_SUPERUSER_ID}),
    )
    event = group_message_event(user_id=_SUPERUSER_ID, group_id=20001)

    assert event_is_feature_allowed(features, event, "seer_pet")


def test_group_event_feature_policy_respects_disabled_superuser_bypass() -> None:
    features = FeatureService(
        FeatureConfig(superuser_bypass=False),
        frozenset({_SUPERUSER_ID}),
    )
    event = group_message_event(user_id=_SUPERUSER_ID, group_id=20001)

    assert not event_is_feature_allowed(features, event, "seer_pet")
