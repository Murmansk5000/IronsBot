# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.authorization import (
    GROUP_MANAGER_ROLES,
    SuperuserPolicy,
    can_manage_group_actor,
)
from ironsbot.integrations.onebot.identity import onebot_actor_ref

if TYPE_CHECKING:
    from ironsbot.core.platform import ActorRef

def event_actor(event: object) -> ActorRef | None:
    user_id = getattr(event, "user_id", None)
    if user_id is None:
        return None
    return onebot_actor_ref(str(user_id))


def is_superuser_event(features: SuperuserPolicy, event: object) -> bool:
    actor = event_actor(event)
    return actor is not None and features.is_actor_superuser(actor)


def is_group_owner_or_admin_event(event: object) -> bool:
    sender = getattr(event, "sender", None)
    return getattr(sender, "role", None) in GROUP_MANAGER_ROLES


def can_manage_group_event(features: SuperuserPolicy, event: object) -> bool:
    actor = event_actor(event)
    if actor is None:
        return False
    sender = getattr(event, "sender", None)
    return can_manage_group_actor(
        features,
        actor,
        getattr(sender, "role", None),
    )


def can_manage_conversation_event(features: SuperuserPolicy, event: object) -> bool:
    if getattr(event, "group_id", None) is not None:
        return can_manage_group_event(features, event)
    return event_actor(event) is not None
