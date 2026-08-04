# SPDX-License-Identifier: MIT
"""OneBot v11 implementation of the platform-neutral outbound port."""

from __future__ import annotations

from base64 import b64encode
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger

from ironsbot.core.outbound import (
    BinaryImagePart,
    DeliveryCapabilities,
    MentionPart,
    OutboundMessage,
    RemoteImagePart,
    ReplyContext,
    SendResult,
    TextPart,
)
from ironsbot.core.platform import ConversationRef, Platform

if TYPE_CHECKING:
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


class OneBotOutboundMessageError(ValueError):
    @classmethod
    def unsupported_mention(cls) -> OneBotOutboundMessageError:
        return cls("OneBot mentions require a numeric group member")

    @classmethod
    def unsupported_part(cls, part: object) -> OneBotOutboundMessageError:
        return cls(f"Unsupported outbound part: {type(part).__name__}")

    @classmethod
    def invalid_reply_id(cls) -> OneBotOutboundMessageError:
        return cls("OneBot reply message IDs must be numeric")


class OneBotOutboundMessenger:
    """Translate core outbound values only after routing to a OneBot bot."""

    def __init__(self, router: BotRouter) -> None:
        self._router = router

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
        return await self._deliver(conversation, message)

    async def reply(
        self,
        context: ReplyContext,
        message: OutboundMessage,
    ) -> SendResult:
        return await self._deliver(
            context.conversation,
            message,
            reply_to_id=context.message_id,
        )

    async def _deliver(
        self,
        conversation: ConversationRef,
        message: OutboundMessage,
        *,
        reply_to_id: str | None = None,
    ) -> SendResult:
        if not _supports_conversation(conversation):
            return SendResult(
                delivered=False,
                error_code="unsupported_conversation",
                error_message=(
                    "OneBot only supports private and group conversations"
                ),
            )
        try:
            rendered = _render_message(
                conversation,
                message,
                reply_to_id=reply_to_id,
            )
        except ValueError as error:
            return SendResult(
                delivered=False,
                error_code="unsupported_message",
                error_message=str(error),
            )
        bot = self._router.for_conversation(conversation)
        if bot is None:
            return SendResult(
                delivered=False,
                error_code="bot_unavailable",
                error_message="No connected OneBot bot can deliver this message",
            )
        try:
            result = await _send_onebot_message(bot, conversation, rendered)
        except Exception as error:  # noqa: BLE001 - delivery boundary
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


def _render_message(
    conversation: ConversationRef,
    message: OutboundMessage,
    *,
    reply_to_id: str | None,
) -> Message:
    rendered = Message()
    if reply_to_id is not None:
        rendered += MessageSegment.reply(_onebot_id(reply_to_id))
    for part in message.parts:
        if isinstance(part, TextPart):
            rendered += MessageSegment.text(part.text)
        elif isinstance(part, BinaryImagePart):
            encoded = b64encode(part.content).decode("ascii")
            rendered += MessageSegment.image(f"base64://{encoded}")
        elif isinstance(part, RemoteImagePart):
            rendered += MessageSegment.image(part.url)
        elif isinstance(part, MentionPart):
            if (
                conversation.kind != "group"
                or part.actor.platform is not Platform.ONEBOT
                or not part.actor.id.isdecimal()
            ):
                raise OneBotOutboundMessageError.unsupported_mention()
            rendered += MessageSegment.at(int(part.actor.id))
        else:
            raise OneBotOutboundMessageError.unsupported_part(part)
    return rendered


async def _send_onebot_message(
    bot: OneBotMessageSender,
    conversation: ConversationRef,
    message: Message,
) -> object:
    target_id = int(conversation.id)
    if conversation.kind == "private":
        return await bot.send_private_msg(user_id=target_id, message=message)
    return await bot.send_group_msg(group_id=target_id, message=message)


def _onebot_id(value: str) -> int:
    if not value.isdecimal():
        raise OneBotOutboundMessageError.invalid_reply_id()
    return int(value)


def _result_message_id(result: object) -> str | None:
    if isinstance(result, dict):
        value: Any = result.get("message_id")
    else:
        value = getattr(result, "message_id", None)
    text = str(value).strip() if value is not None else ""
    return text or None
