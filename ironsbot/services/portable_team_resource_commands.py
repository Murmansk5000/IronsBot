# SPDX-License-Identifier: MIT
"""Portable command operations for team-resource subscriptions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import GROUP_MANAGER_ROLES
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.portable_query_sessions import PortableMenuSpec
from ironsbot.services.seer.team import TeamQueryActor
from ironsbot.services.team.overview import format_team_overview
from ironsbot.services.team.resource_subscriptions import (
    TeamResourceSubscriptionTarget,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.team import SeerTeamQueryService
    from ironsbot.services.team.overview import TeamOverviewItem
    from ironsbot.services.team.resource import TeamResourceService

logger = logging.getLogger(__name__)


def build_portable_team_resource_operations(
    service: TeamResourceService,
    player_id_resolver: PlayerIdResolver,
    team_query: SeerTeamQueryService,
    sessions: PortableQuerySessions,
) -> Mapping[str, PortableOperation]:
    """Bind portable command IDs to the existing domain service."""

    async def query(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        target = _target(context)
        actor = _team_query_actor(context, service)
        first_team_id = await _bound_team_id(
            context,
            player_id_resolver,
            team_query,
        )
        items = await service.query_overview(target, first_team_id=first_team_id)
        if not items:
            return OutboundMessage.from_text(service.subscriptions_message(target))

        async def select(item: TeamOverviewItem) -> OutboundMessage:
            return OutboundMessage.from_text(
                await team_query.query((item.team_id,), actor)
            )

        return sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=items,
                labels=tuple(item.name or str(item.team_id) for item in items),
                select=select,
                prompt=OutboundMessage.from_text(format_team_overview(items)),
                keep_open=True,
                exit_message="已退出战队查询。",
            ),
        )

    async def manage(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        command = service.parse_manage(text)
        if command is None:
            msg = (
                "catalog accepted input that its team resource parser rejected: "
                f"{text!r}"
            )
            raise ValueError(msg)
        target = _target(context)
        if command.action == "list":
            result = service.subscriptions_message(target)
        elif command.team_id is None:
            msg = f"team resource command has no team id: {text!r}"
            raise ValueError(msg)
        elif command.action == "remove":
            result = service.remove_target_subscription(
                target=target,
                team_id=command.team_id,
            )
        elif (
            command.has_manual_mention
            and target.is_group
            and not target.mention_actors
        ):
            result = (
                "提醒对象要使用平台的 @ 选人功能添加；"
                "手动输入 @账号 不会保存为提醒对象。"
            )
        else:
            result = await service.add_target_subscription(
                target=target,
                team_id=command.team_id,
                threshold=command.threshold,
                operator=context.message.actor,
            )
        return OutboundMessage.from_text(result)

    return {
        "team_resource.query": query,
        "team_resource.subscribe": manage,
        "team_resource.unsubscribe": manage,
        "team_resource.list": manage,
    }


async def _bound_team_id(
    context: MessageInputContext,
    player_id_resolver: PlayerIdResolver,
    team_query: SeerTeamQueryService,
) -> int | None:
    resolution = player_id_resolver.resolve(context, None)
    if resolution.player_id is None:
        return None
    lookup = await team_query.lookup_player_team(resolution.player_id)
    if lookup.error is not None:
        logger.info(
            "bound player team lookup skipped: player_id=%s reason=%s",
            resolution.player_id,
            lookup.error,
        )
    return lookup.team_id


def _team_query_actor(
    context: MessageInputContext,
    service: TeamResourceService,
) -> TeamQueryActor:
    message = context.message
    return TeamQueryActor(
        actor=message.actor,
        conversation=message.conversation,
        can_manage=(
            message.group_role in GROUP_MANAGER_ROLES
            or service.is_superuser(message.actor)
        ),
    )


def _target(context: MessageInputContext) -> TeamResourceSubscriptionTarget:
    message = context.message
    if message.conversation.kind == "group":
        return TeamResourceSubscriptionTarget(
            message.conversation,
            context.member_mentions,
        )
    return TeamResourceSubscriptionTarget(message.actor)
