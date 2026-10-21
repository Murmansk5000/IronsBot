# SPDX-License-Identifier: MIT
"""Bind a team subscription suggestion to its operator's public menu session."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.authorization import GROUP_MANAGER_ROLES
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.services.portable_query_sessions import PortableMenuSpec
from ironsbot.services.team.resource_subscriptions import TeamResourceSubscriptionTarget

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.team.resource import TeamResourceService


def subscription_confirmation(
    service: TeamResourceService,
    message: OutboundMessage,
    context: MessageInputContext,
    sessions: PortableQuerySessions,
) -> OutboundMessage:
    text = "".join(part.text for part in message.parts if isinstance(part, TextPart))
    if "是否订阅这个战队？" not in text:
        return message
    pending = service.pending_prompt(context.message.conversation)
    if pending is None or pending.prompted_by != context.message.actor:
        return message

    def allowed(selected: MessageInputContext) -> bool:
        current = selected.message
        return (
            current.actor == pending.prompted_by
            and current.conversation == pending.conversation
            and (
                current.group_role in GROUP_MANAGER_ROLES
                or service.is_superuser(current.actor)
            )
            and service.allows_target(
                current.actor,
                TeamResourceSubscriptionTarget(current.conversation),
            )
        )

    async def select(accepted: bool, selected: MessageInputContext) -> OutboundMessage:  # noqa: FBT001
        if service.pending_prompt(selected.message.conversation) != pending:
            return OutboundMessage.from_text("该订阅建议已失效，请重新查询。")
        result = service.answer_prompt(
            conversation=selected.message.conversation,
            actor=selected.message.actor,
            accepted=accepted,
        )
        return OutboundMessage.from_text(result or "该订阅建议已失效，请重新查询。")

    return sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=(True, False),
            labels=("订阅", "跳过"),
            text_inputs=(frozenset({"是", "y"}), frozenset({"否", "n"})),
            select=select,
            access=allowed,
            prompt=OutboundMessage.from_text(text + "\n0.【取消】"),
            exit_message="已取消战队订阅确认。",
            exit_label="取消",
        ),
    )
