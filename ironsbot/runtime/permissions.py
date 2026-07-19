# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Protocol

GROUP_MANAGER_ROLES = frozenset({"owner", "admin"})


class SuperuserPolicy(Protocol):
    def is_superuser(self, user_id: int) -> bool: ...


def event_user_id(event: object) -> int | None:
    user_id = getattr(event, "user_id", None)
    if user_id is None:
        return None
    return int(user_id)


def is_superuser_event(features: SuperuserPolicy, event: object) -> bool:
    user_id = event_user_id(event)
    return user_id is not None and features.is_superuser(user_id)


def is_group_owner_or_admin_event(event: object) -> bool:
    sender = getattr(event, "sender", None)
    return getattr(sender, "role", None) in GROUP_MANAGER_ROLES


def can_manage_group_event(features: SuperuserPolicy, event: object) -> bool:
    return is_superuser_event(features, event) or is_group_owner_or_admin_event(event)


def can_manage_conversation_event(features: SuperuserPolicy, event: object) -> bool:
    if getattr(event, "group_id", None) is not None:
        return can_manage_group_event(features, event)
    return is_superuser_event(features, event)
