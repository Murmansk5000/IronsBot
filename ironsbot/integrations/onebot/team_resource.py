# SPDX-License-Identifier: MIT
"""OneBot configuration adapter for team resource subscriptions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, Platform

if TYPE_CHECKING:
    from ironsbot.config.models.seer import TeamResourceConfig
    from ironsbot.config.onebot_references import OneBotReferenceResolver


def build_onebot_team_resource_default_mentions(
    config: TeamResourceConfig,
    references: OneBotReferenceResolver,
) -> tuple[ActorRef, ...]:
    """Resolve OneBot-only TOML aliases before the service is composed."""

    return tuple(
        ActorRef(Platform.ONEBOT, str(user_id))
        for user_id in references.resolve_users(
            config.default_at_users,
            location="seer.team_resource.default_at_users",
        )
    )
