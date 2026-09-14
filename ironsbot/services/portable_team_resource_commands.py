# SPDX-License-Identifier: MIT
"""Portable command operations for team-resource subscriptions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.semantic_requests import ActionDefinition, SemanticTarget
from ironsbot.services.portable_seer_commands import team_query_actor
from ironsbot.services.seer.query_result import QueryChoice, QueryResult
from ironsbot.services.team.resource_subscriptions import (
    TeamResourceSubscriptionTarget,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.team import SeerTeamQueryService
    from ironsbot.services.team.resource import TeamResourceService


def build_portable_team_resource_operations(
    service: TeamResourceService,
    *,
    query: PortableOperation,
) -> Mapping[str, PortableOperation]:
    """Bind portable command IDs to the existing domain service."""

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


def build_portable_team_overview_operation(
    service: TeamResourceService,
    teams: SeerTeamQueryService,
    resolver: PlayerIdResolver,
    features: FeatureService,
    sessions: PortableQuerySessions,
) -> PortableOperation:
    async def query(text: str, context: MessageInputContext) -> OutboundMessage:
        del text
        target = _target(context)
        if not service.allows_target(context.message.actor, target):
            return OutboundMessage.from_text("该功能当前未对你开放。")
        bound = resolver.resolve(context, None)
        first_team_id = None
        error = bound.error
        if bound.player_id is not None:
            lookup = await teams.lookup_player_team(
                bound.player_id, team_query_actor(features, context)
            )
            first_team_id, error = lookup.team_id, lookup.error
        items = await service.query_overview(target, first_team_id=first_team_id)
        if not items:
            return OutboundMessage.from_text(
                error or service.subscriptions_message(target)
            )

        async def select(team_id: int) -> OutboundMessage:
            if not service.allows_target(context.message.actor, target):
                return OutboundMessage.from_text("该功能当前未对你开放。")
            return OutboundMessage.from_text(
                await teams.query((team_id,), team_query_actor(features, context))
            )

        result = QueryResult(
            choices=tuple(
                QueryChoice(
                    name=f"【{item.team_id}】{item.name}",
                    description=item.description,
                    value=item.team_id,
                    semantic_target=SemanticTarget(
                        f"team:{item.team_id}", str(item.team_id)
                    ),
                    semantic_action=ActionDefinition(
                        "team_resource.query", "战队查询", "team_resource_query"
                    ),
                )
                for item in items
            )
        )
        return sessions.offer(
            context,
            result,
            select=select,
            prompt_title="当前战队信息概览：" + (f"\n{error}" if error else ""),
            not_found_message="没有可查询的战队。",
            keep_open=True,
        )

    return query


def _target(context: MessageInputContext) -> TeamResourceSubscriptionTarget:
    message = context.message
    if message.conversation.kind == "group":
        return TeamResourceSubscriptionTarget(
            message.conversation,
            context.member_mentions,
        )
    return TeamResourceSubscriptionTarget(message.actor)
