from ironsbot.shared.messaging.targets import (
    MessageTarget,
    broadcast_targets,
    group_targets,
    message_event_target,
    private_targets,
)
from tests.helpers.onebot_events import group_message_event, private_message_event


def test_private_targets_deduplicate_users() -> None:
    assert private_targets([1, 1, 2]) == [
        MessageTarget("private", 1),
        MessageTarget("private", 2),
    ]


def test_group_targets_deduplicate_groups_and_mentions() -> None:
    assert group_targets([10, 10, 20], at_user_ids=[1, 1, 2]) == [
        MessageTarget("group", 10, (1, 2)),
        MessageTarget("group", 20, (1, 2)),
    ]


def test_broadcast_targets_keep_groups_before_private_users() -> None:
    assert broadcast_targets(
        group_ids=[10],
        private_user_ids=[1],
        group_at_user_ids=[2],
    ) == [
        MessageTarget("group", 10, (2,)),
        MessageTarget("private", 1),
    ]


def test_message_event_target_uses_conversation_scope() -> None:
    assert message_event_target(group_message_event(group_id=10)) == MessageTarget(
        "group", 10
    )
    assert message_event_target(private_message_event(user_id=20)) == MessageTarget(
        "private", 20
    )
