# SPDX-License-Identifier: MIT
"""Shared command operation for team and player-team queries."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import GROUP_MANAGER_ROLES
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.player_reference_selection import select_player_reference
from ironsbot.services.seer.query_commands import team_query_argument
from ironsbot.services.seer.team import TeamQueryActor

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation, PortableReply
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.team import SeerTeamQueryService


def build_team_query_operation(
    service: SeerTeamQueryService,
    resolver: PlayerIdResolver,
    features: FeatureService,
    sessions: PortableQuerySessions,
) -> PortableOperation:
    """Bind the team-query use case once for every message adapter."""

    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage | PortableReply:
        parsed = team_query_argument(text)
        if parsed is None:
            msg = f"invalid team query input: {text!r}"
            raise ValueError(msg)
        reference = parsed.argument.strip()
        message = context.message
        actor = TeamQueryActor(
            message.actor,
            message.conversation,
            (
                message.group_role in GROUP_MANAGER_ROLES
                or features.is_actor_superuser(message.actor)
            ),
        )
        if not context.has_member_mentions and re.fullmatch(
            r"\d+(?:\s+\d+)*", reference
        ):
            return OutboundMessage.from_text(
                await service.query(service.parse_team_ids(reference), actor),
            )
        reference = reference.removeprefix("米米号").strip()

        async def query_player(player_id: int) -> OutboundMessage:
            return OutboundMessage.from_text(
                await service.query_player_team(player_id, actor)
            )

        if reference and not context.has_member_mentions:
            return await select_player_reference(
                reference,
                context,
                resolver,
                sessions,
                query_player,
                title="请选择要查询所属战队的玩家：",
            )
        resolution = resolver.resolve(context, reference, allow_default_binding=False)
        if resolution.error is not None:
            return OutboundMessage.from_text(resolution.error)
        if resolution.player_id is None:
            return OutboundMessage.from_text(
                "请填写战队号、米米号、玩家别名，或直接 @ 一名已绑定成员。",
            )
        return await query_player(resolution.player_id)

    return execute
