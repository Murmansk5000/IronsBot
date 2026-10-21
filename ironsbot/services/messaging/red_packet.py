# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.config.models.messaging import RedPacketNoticeConfig
    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.services.messaging.admin_notice import (
        AdminNoticeSendSummary,
        AdminNoticeService,
    )

from ironsbot.core.platform import reference_digest
from ironsbot.services.messaging.rate_limits import SlidingWindowRateLimiter

logger = logging.getLogger(__name__)
RED_PACKET_NOTICE_SUBSCRIPTION_KEY = "red_packet_notice"


@dataclass(slots=True)
class RedPacketNoticeService:
    config: RedPacketNoticeConfig
    admin_notices: AdminNoticeService
    limiter: SlidingWindowRateLimiter = field(default_factory=SlidingWindowRateLimiter)

    def admit(self, context: CommandContext, *, now: float | None = None) -> bool:
        if not self.config.enabled or not context.is_group:
            return False
        allowed = (
            self.limiter.hit(
                RED_PACKET_NOTICE_SUBSCRIPTION_KEY,
                context.conversation,
                window_seconds=self.config.cooldown_seconds,
                max_events=1,
                now=now,
            )
            >= 0
        )
        if not allowed:
            logger.info(
                "red packet notice suppressed by cooldown: conversation_ref=%s",
                reference_digest(context.conversation.id),
            )
        return allowed

    async def handle(
        self,
        context: CommandContext,
        *,
        summary: str,
        conversation_name: Callable[[], Awaitable[str]],
    ) -> AdminNoticeSendSummary | None:
        if not self.admit(context):
            return None
        conversation = context.conversation
        logger.info(
            "red packet notice detected: conversation_ref=%s actor_ref=%s",
            reference_digest(conversation.id),
            reference_digest(context.actor.id),
        )
        notice = build_red_packet_notice_message(
            conversation=conversation,
            conversation_name=await conversation_name(),
            sender=context.actor,
            summary=summary,
        )
        return await self.admin_notices.send(
            notice,
            action_name="red packet notice",
            subscription_key=RED_PACKET_NOTICE_SUBSCRIPTION_KEY,
        )


def build_red_packet_notice_message(
    *,
    conversation: ConversationRef,
    conversation_name: str = "",
    sender: ActorRef,
    summary: str = "",
) -> str:
    group_label = (
        f"{conversation_name}（{conversation.id}）"
        if conversation_name
        else conversation.id
    )
    lines = [
        "🧧 检测到群红包",
        f"群：{group_label}",
        f"发送者：{sender.id}",
    ]
    if summary:
        lines.append(f"内容：{summary}")
    return "\n".join(lines)
