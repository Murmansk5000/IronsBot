# SPDX-License-Identifier: MIT
"""Portable command operations for team-resource subscriptions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.team.resource_subscriptions import (
    TeamResourceSubscriptionTarget,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.team.resource import TeamResourceService


def build_portable_team_resource_operations(
    service: TeamResourceService,
) -> Mapping[str, PortableOperation]:
    """Bind portable command IDs to the existing domain service."""

    async def query(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        target = _target(context)
        messages = await service.query_target_messages(target)
        text = "\n\n".join(messages) or service.subscriptions_message(target)
        return OutboundMessage.from_text(text)

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


def _target(context: MessageInputContext) -> TeamResourceSubscriptionTarget:
    message = context.message
    if message.conversation.kind == "group":
        return TeamResourceSubscriptionTarget(
            message.conversation,
            context.member_mentions,
        )
    return TeamResourceSubscriptionTarget(message.actor)
