from ironsbot.config.models.feature import FeatureConfig
from ironsbot.services.bilibili import permissions
from ironsbot.shared.features import FeatureService
from tests.helpers.onebot_events import private_message_event


def test_dynamic_update_requires_bili_superuser() -> None:
    features = FeatureService(FeatureConfig(), frozenset({42}))

    assert permissions.is_dynamic_update_allowed(
        features,
        private_message_event(user_id=42),
    )
    assert not permissions.is_dynamic_update_allowed(
        features,
        private_message_event(user_id=7),
    )


def test_dynamic_query_uses_feature_service() -> None:
    features = FeatureService(
        FeatureConfig(user_policy={"42": ["bili_query"]}),
        frozenset(),
    )

    assert permissions.is_dynamic_query_allowed(
        features,
        private_message_event(user_id=42),
    )
    assert not permissions.is_dynamic_query_allowed(
        features,
        private_message_event(user_id=7),
    )
