from ironsbot.core.features import FeatureConfig, FeatureService
from ironsbot.plugins.messaging.blacklist import event_is_blacklisted
from tests.helpers.onebot_events import group_message_event, private_message_event


def test_blacklist_rule_blocks_a_configured_user_in_private_and_group() -> None:
    features = FeatureService(
        FeatureConfig(user_policy={"123": ["blacklist"]}),
        frozenset(),
    )

    assert event_is_blacklisted(features, private_message_event(user_id=123))
    assert event_is_blacklisted(features, group_message_event(user_id=123))


def test_blacklist_rule_blocks_every_user_in_a_configured_group() -> None:
    features = FeatureService(
        FeatureConfig(group_policy={"456": ["blacklist"]}),
        frozenset(),
    )

    assert event_is_blacklisted(
        features,
        group_message_event(user_id=999, group_id=456),
    )
    assert not event_is_blacklisted(
        features,
        group_message_event(user_id=999, group_id=654),
    )
