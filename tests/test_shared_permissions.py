# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.shared import permissions
from tests.helpers.onebot_events import (
    group_admin_message_event,
    group_member_message_event,
    group_owner_message_event,
)

if TYPE_CHECKING:
    from pytest import MonkeyPatch


def test_can_manage_group_event_allows_group_owner(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(permissions, "is_superuser_event", lambda _event: False)

    assert permissions.can_manage_group_event(group_owner_message_event())


def test_can_manage_group_event_allows_group_admin(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(permissions, "is_superuser_event", lambda _event: False)

    assert permissions.can_manage_group_event(group_admin_message_event())


def test_can_manage_group_event_allows_superuser(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(permissions, "is_superuser_event", lambda _event: True)

    assert permissions.can_manage_group_event(group_member_message_event())


def test_can_manage_group_event_rejects_regular_member(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(permissions, "is_superuser_event", lambda _event: False)

    assert not permissions.can_manage_group_event(group_member_message_event())
