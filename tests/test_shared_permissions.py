# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.config.models.feature import FeatureConfig
from ironsbot.shared import permissions
from ironsbot.shared.features import FeatureService
from tests.helpers.onebot_events import (
    group_admin_message_event,
    group_member_message_event,
    group_owner_message_event,
    private_message_event,
)

REGULAR_FEATURES = FeatureService(FeatureConfig(), frozenset())
SUPERUSER_FEATURES = FeatureService(FeatureConfig(), frozenset({123}))


def test_can_manage_group_event_allows_group_owner() -> None:
    assert permissions.can_manage_group_event(
        REGULAR_FEATURES,
        group_owner_message_event(),
    )


def test_can_manage_group_event_allows_group_admin() -> None:
    assert permissions.can_manage_group_event(
        REGULAR_FEATURES,
        group_admin_message_event(),
    )


def test_can_manage_group_event_allows_superuser() -> None:
    assert permissions.can_manage_group_event(
        SUPERUSER_FEATURES,
        group_member_message_event(),
    )


def test_can_manage_group_event_rejects_regular_member() -> None:
    assert not permissions.can_manage_group_event(
        REGULAR_FEATURES,
        group_member_message_event(),
    )


def test_can_manage_conversation_event_allows_group_manager() -> None:
    assert permissions.can_manage_conversation_event(
        REGULAR_FEATURES,
        group_admin_message_event(),
    )


def test_can_manage_conversation_event_allows_private_superuser() -> None:
    assert permissions.can_manage_conversation_event(
        SUPERUSER_FEATURES,
        private_message_event(),
    )


def test_can_manage_conversation_event_rejects_regular_private_user() -> None:
    assert not permissions.can_manage_conversation_event(
        REGULAR_FEATURES,
        private_message_event(),
    )
