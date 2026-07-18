# SPDX-License-Identifier: MIT
from ironsbot.config.models.feature import FeatureConfig
from ironsbot.plugins.bilibili import account_commands
from ironsbot.shared.features import FeatureService
from tests.helpers.onebot_events import (
    group_admin_message_event,
    group_member_message_event,
    private_message_event,
)

SUPERUSER_ID = 1001
REGULAR_USER_ID = 2002
FEATURES = FeatureService(FeatureConfig(), frozenset({SUPERUSER_ID}))


def test_bili_push_mode_manager_allows_group_admin() -> None:
    assert account_commands._is_bili_push_mode_manager(
        FEATURES,
        group_admin_message_event(),
    )


def test_bili_push_mode_manager_rejects_group_member() -> None:
    assert not account_commands._is_bili_push_mode_manager(
        FEATURES,
        group_member_message_event(),
    )


def test_bili_push_mode_manager_allows_private_superuser() -> None:
    assert account_commands._is_bili_push_mode_manager(
        FEATURES,
        private_message_event(user_id=SUPERUSER_ID),
    )
    assert not account_commands._is_bili_push_mode_manager(
        FEATURES,
        private_message_event(user_id=REGULAR_USER_ID),
    )
