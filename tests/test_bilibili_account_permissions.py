# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.plugins.bilibili import account_commands
from ironsbot.shared import permissions
from tests.helpers.onebot_events import (
    group_admin_message_event,
    group_member_message_event,
    private_message_event,
)

if TYPE_CHECKING:
    from pytest import MonkeyPatch

SUPERUSER_ID = 1001
REGULAR_USER_ID = 2002


def test_bili_push_mode_manager_allows_group_admin(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(permissions, "is_superuser", lambda _user_id: False)

    assert account_commands._is_bili_push_mode_manager(
        group_admin_message_event()
    )


def test_bili_push_mode_manager_rejects_group_member(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(permissions, "is_superuser", lambda _user_id: False)

    assert not account_commands._is_bili_push_mode_manager(
        group_member_message_event()
    )


def test_bili_push_mode_manager_allows_private_superuser(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        permissions,
        "is_superuser",
        lambda user_id: user_id == SUPERUSER_ID,
    )

    assert account_commands._is_bili_push_mode_manager(
        private_message_event(user_id=SUPERUSER_ID)
    )
    assert not account_commands._is_bili_push_mode_manager(
        private_message_event(user_id=REGULAR_USER_ID)
    )
