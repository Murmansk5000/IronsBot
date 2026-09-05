"""Test-only transport policy, not an implementation of QQ's actual API."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from ironsbot.core.outbound import (
    BinaryImagePart,
    DeliveryCapabilities,
    MentionPart,
    OutboundMessage,
    RemoteImagePart,
    ReplyContext,
    SendResult,
)
from ironsbot.core.platform import Platform

if TYPE_CHECKING:
    from datetime import datetime

    from ironsbot.core.platform import ConversationRef


RESTRICTED_CAPABILITIES = DeliveryCapabilities(
    can_reply_to_event=True,
    can_send_proactively=False,
    can_mention_members=True,
    supports_group_context=True,
    supports_private_context=True,
    supports_images=True,
)


@dataclass
class FakeOfficialPlatform:
    now: datetime
    capabilities: DeliveryCapabilities = RESTRICTED_CAPABILITIES
    failure: SendResult | None = None
    attempts: list[tuple[ConversationRef, OutboundMessage]] = field(
        default_factory=list
    )
    replies: list[ReplyContext] = field(default_factory=list)
    uploads: list[BinaryImagePart] = field(default_factory=list)

    def capabilities_for(self, conversation: ConversationRef) -> DeliveryCapabilities:
        supported = conversation.platform is Platform.QQ_OFFICIAL and (
            (conversation.kind == "group" and self.capabilities.supports_group_context)
            or (
                conversation.kind == "private"
                and self.capabilities.supports_private_context
            )
        )
        if supported:
            return self.capabilities
        return DeliveryCapabilities(
            can_reply_to_event=False,
            can_send_proactively=False,
            can_mention_members=False,
            supports_group_context=False,
            supports_private_context=False,
            supports_images=False,
        )

    async def send(
        self, conversation: ConversationRef, message: OutboundMessage
    ) -> SendResult:
        self.attempts.append((conversation, message))
        if not self.capabilities_for(conversation).can_send_proactively:
            return self._error("proactive_denied")
        return self._deliver(conversation, message)

    async def reply(
        self, context: ReplyContext, message: OutboundMessage
    ) -> SendResult:
        self.replies.append(context)
        self.attempts.append((context.conversation, message))
        if not self.capabilities_for(context.conversation).can_reply_to_event:
            return self._error("reply_denied")
        if context.reply_deadline is not None and self.now >= context.reply_deadline:
            return self._error("reply_expired")
        return self._deliver(context.conversation, message)

    def _deliver(
        self, conversation: ConversationRef, message: OutboundMessage
    ) -> SendResult:
        capabilities = self.capabilities_for(conversation)
        for part in message.parts:
            if isinstance(part, (BinaryImagePart, RemoteImagePart)):
                if not capabilities.supports_images:
                    return self._error("images_denied")
            elif isinstance(part, MentionPart):
                if not capabilities.can_mention_members:
                    return self._error("mentions_denied")
                if (
                    part.actor.platform is not conversation.platform
                    or conversation.kind != "group"
                    or part.actor.kind != "member"
                    or part.actor.scope_id != conversation.id
                ):
                    return self._error("mention_scope")
        if self.failure is not None:
            return replace(self.failure, trace_id=self._trace_id())
        self.uploads.extend(
            part for part in message.parts if isinstance(part, BinaryImagePart)
        )
        return SendResult(
            delivered=True,
            message_id=f"fake-message-{len(self.attempts)}",
            trace_id=self._trace_id(),
        )

    def _trace_id(self) -> str:
        return f"fake-trace-{len(self.attempts)}"

    def _error(self, code: str) -> SendResult:
        return SendResult(
            delivered=False, error_code=f"fake_{code}", trace_id=self._trace_id()
        )
