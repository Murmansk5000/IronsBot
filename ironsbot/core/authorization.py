# SPDX-License-Identifier: MIT
"""Platform-neutral authorization vocabulary used by command policies."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ironsbot.core.platform import ActorRef

GROUP_MANAGER_ROLES = frozenset({"owner", "admin"})


class SuperuserPolicy(Protocol):
    def is_actor_superuser(self, actor: ActorRef) -> bool: ...


def can_manage_group_actor(
    features: SuperuserPolicy,
    actor: ActorRef,
    group_role: str | None,
) -> bool:
    """Authorize one normalized group actor without transport-specific events."""

    return group_role in GROUP_MANAGER_ROLES or features.is_actor_superuser(actor)
