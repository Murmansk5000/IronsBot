from ironsbot.integrations.onebot.targets import (
    OneBotMessageTarget,
    broadcast_targets,
    group_targets,
    private_targets,
)


def test_private_targets_deduplicate_users() -> None:
    assert private_targets([1, 1, 2]) == [
        OneBotMessageTarget("private", 1),
        OneBotMessageTarget("private", 2),
    ]


def test_group_targets_deduplicate_groups_and_mentions() -> None:
    assert group_targets([10, 10, 20], at_user_ids=[1, 1, 2]) == [
        OneBotMessageTarget("group", 10, (1, 2)),
        OneBotMessageTarget("group", 20, (1, 2)),
    ]


def test_broadcast_targets_keep_groups_before_private_users() -> None:
    assert broadcast_targets(
        group_ids=[10],
        private_user_ids=[1],
        group_at_user_ids=[2],
    ) == [
        OneBotMessageTarget("group", 10, (2,)),
        OneBotMessageTarget("private", 1),
    ]
