# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.shared.features import is_superuser

GROUP_MANAGER_ROLES = frozenset({"owner", "admin"})


def event_user_id(event: object) -> int | None:
    user_id = getattr(event, "user_id", None)
    if user_id is None:
        return None
    return int(user_id)


def is_superuser_event(event: object) -> bool:
    user_id = event_user_id(event)
    return user_id is not None and is_superuser(user_id)


def is_group_owner_or_admin_event(event: object) -> bool:
    sender = getattr(event, "sender", None)
    role = getattr(sender, "role", None)
    return role in GROUP_MANAGER_ROLES


def can_manage_group_event(event: object) -> bool:
    return is_superuser_event(event) or is_group_owner_or_admin_event(event)


def can_manage_conversation_event(event: object) -> bool:
    if getattr(event, "group_id", None) is not None:
        return can_manage_group_event(event)
    return is_superuser_event(event)


__all__ = [
    "GROUP_MANAGER_ROLES",
    "can_manage_conversation_event",
    "can_manage_group_event",
    "event_user_id",
    "is_group_owner_or_admin_event",
    "is_superuser_event",
]
