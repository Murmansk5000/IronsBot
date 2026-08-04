# SPDX-License-Identifier: MIT
"""OneBot v11 implementation of the platform-neutral outbound port."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot.log import logger

from ironsbot.core.outbound import (
    DeliveryCapabilities,
    OutboundMessage,
    ReplyContext,
    SendResult,
)
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.onebot.message_rendering import (
    OneBotOutboundMessageError,
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.outbound import (
    GroupOutboundRateLimitService,
    use_preacquired_push_permit,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message

    from ironsbot.integrations.onebot.delivery import OneBotMessageSender
    from ironsbot.integrations.onebot.router import BotRouter


_ONEBOT_CAPABILITIES = DeliveryCapabilities(
    can_reply_to_event=True,
    can_send_proactively=True,
    can_mention_members=True,
    supports_group_context=True,
    supports_private_context=True,
    supports_images=True,
)
_UNSUPPORTED_CAPABILITIES = DeliveryCapabilities(
    can_reply_to_event=False,
    can_send_proactively=False,
    can_mention_members=False,
    supports_group_context=False,
    supports_private_context=False,
    supports_images=False,
)


class OneBotOutboundMessenger:
    """Translate core outbound values only after routing to a OneBot bot."""

    def __init__(
        self,
        router: BotRouter,
        outbound: GroupOutboundRateLimitService,
    ) -> None:
        self._router = router
        self._outbound = outbound

    def capabilities_for(
        self,
        conversation: ConversationRef,
    ) -> DeliveryCapabilities:
        return (
            _ONEBOT_CAPABILITIES
            if _supports_conversation(conversation)
            else _UNSUPPORTED_CAPABILITIES
        )

    async def send(
        self,
        conversation: ConversationRef,
        message: OutboundMessage,
    ) -> SendResult:
        return await self._deliver(conversation, message, proactive=True)

    async def reply(
        self,
        context: ReplyContext,
        message: OutboundMessage,
    ) -> SendResult:
        return await self._deliver(
            context.conversation,
            message,
            reply_to_id=context.message_id,
            proactive=False,
        )

    async def _deliver(
        self,
        conversation: ConversationRef,
        message: OutboundMessage,
        *,
        reply_to_id: str | None = None,
        proactive: bool,
    ) -> SendResult:
        if not _supports_conversation(conversation):
            return SendResult(
                delivered=False,
                error_code="unsupported_conversation",
                error_message=("OneBot only supports private and group conversations"),
            )
        try:
            rendered = render_onebot_outbound_message(
                message,
                conversation=conversation,
                reply_to_id=reply_to_id,
            )
        except OneBotOutboundMessageError as error:
            return SendResult(
                delivered=False,
                error_code="unsupported_message",
                error_message=str(error),
            )
        return await self._send_rendered(
            conversation,
            rendered,
            proactive=proactive,
        )

    async def _send_rendered(
        self,
        conversation: ConversationRef,
        rendered: Message,
        *,
        proactive: bool,
    ) -> SendResult:
        bot = self._router.for_conversation(conversation)
        if bot is None:
            return SendResult(
                delivered=False,
                error_code="bot_unavailable",
                error_message="No connected OneBot bot can deliver this message",
            )
        decision = (
            await self._outbound.acquire_push(
                _group_id(conversation),
                source="platform outbound",
            )
            if proactive
            else None
        )
        if decision is not None and not decision.allowed:
            return SendResult(
                delivered=False,
                error_code=decision.reason or "rate_limit",
                error_message="Outbound group message is rate limited",
            )
        try:
            with use_preacquired_push_permit(
                self._outbound,
                decision.permit if decision is not None else None,
            ):
                result = await _send_onebot_message(bot, conversation, rendered)
        except Exception as error:  # noqa: BLE001 - delivery boundary
            if decision is not None:
                self._outbound.rollback(decision.permit)
            logger.warning(
                "OneBot outbound delivery failed: kind={} id={} error={}",
                conversation.kind,
                conversation.id,
                error,
            )
            return SendResult(
                delivered=False,
                error_code="delivery_failed",
                error_message=str(error),
            )
        message_id = _result_message_id(result)
        if message_id is None:
            return SendResult(
                delivered=False,
                error_code="missing_message_id",
                error_message="OneBot send response did not include message_id",
            )
        return SendResult(delivered=True, message_id=message_id)


def _supports_conversation(conversation: ConversationRef) -> bool:
    return (
        conversation.platform is Platform.ONEBOT
        and conversation.kind in {"private", "group"}
        and conversation.id.isdecimal()
        and int(conversation.id) > 0
    )


def _group_id(conversation: ConversationRef) -> int | None:
    return int(conversation.id) if conversation.kind == "group" else None


async def _send_onebot_message(
    bot: OneBotMessageSender,
    conversation: ConversationRef,
    message: Message,
) -> object:
    target_id = int(conversation.id)
    if conversation.kind == "private":
        return await bot.send_private_msg(user_id=target_id, message=message)
    return await bot.send_group_msg(group_id=target_id, message=message)


def _result_message_id(result: object) -> str | None:
    if isinstance(result, dict):
        value: Any = result.get("message_id")
    else:
        value = getattr(result, "message_id", None)
    text = str(value).strip() if value is not None else ""
    return text or None
