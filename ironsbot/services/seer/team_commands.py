# SPDX-License-Identifier: MIT
"""Shared command operation for team and player-team queries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import GROUP_MANAGER_ROLES
from ironsbot.core.outbound import OutboundMessage

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.team import SeerTeamQueryService


def build_team_query_operation(
    service: SeerTeamQueryService,
    resolver: PlayerIdResolver,
    features: FeatureService,
) -> PortableOperation:
    """Bind the team-query use case once for every message adapter."""

    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        message = context.message
        result = await service.query_input(
            text,
            context,
            resolver,
            can_manage=(
                message.group_role in GROUP_MANAGER_ROLES
                or features.is_actor_superuser(message.actor)
            ),
        )
        return OutboundMessage.from_text(result)

    return execute
