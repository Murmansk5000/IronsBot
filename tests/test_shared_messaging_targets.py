from ironsbot.shared.messaging.targets import (
    MessageTarget,
    broadcast_targets,
    group_targets,
    private_targets,
)


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
