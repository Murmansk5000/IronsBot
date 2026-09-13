# SPDX-License-Identifier: MIT
"""Install the first production QQ Official passive-command runtime."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from nonebot import on_message
from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves annotations
from nonebot.adapters.qq import Bot as QQOfficialBot  # noqa: TC002
from nonebot.adapters.qq.event import (
    C2CMessageCreateEvent,
    GroupAtMessageCreateEvent,
    GroupMessageCreateEvent,
    QQMessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.rule import Rule

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage
from ironsbot.integrations.qq_official.identity import (
    is_qq_official_reply_event,
    qq_official_incoming_message,
)
from ironsbot.services.portable_commands import PortableCommandRouter  # noqa: TC001

if TYPE_CHECKING:
    from ironsbot.core.outbound import OutboundMessenger, SendResult
    from ironsbot.core.platform import IncomingMessageRef
    from ironsbot.services.portable_reply import PortableReply

logger = logging.getLogger(__name__)


def install_qq_official_runtime(
    router: PortableCommandRouter,
    messenger: OutboundMessenger,
) -> None:
    """Register passive group/C2C handlers against nonebot-adapter-qq."""

    async def accepts(bot: QQOfficialBot, event: Event) -> bool:
        return qq_official_event_is_supported(bot, event, router)

    async def handle(
        event: QQMessageEvent,
        matcher: Matcher,
        bot: QQOfficialBot,
    ) -> None:
        incoming = qq_official_incoming_message(event, account_id=bot.self_id)
        reply = await router.dispatch(
            MessageInputContext(
                incoming,
                mentions_bot=qq_official_event_mentions_bot(event),
            )
        )
        if reply is None:
            return
        await deliver_qq_official_reply(messenger, incoming, reply)
        matcher.stop_propagation()

    matcher = on_message(
        rule=Rule(accepts),
        priority=10,
        block=True,
    )
    matcher.append_handler(handle)
    logger.info("QQ Official passive-command runtime installed")


async def deliver_qq_official_reply(
    messenger: OutboundMessenger,
    incoming: IncomingMessageRef,
    reply: PortableReply,
) -> None:
    """Commit delivery-aware work only after the adapter accepts the reply."""

    from ironsbot.core.outbound import ReplyContext

    context = ReplyContext.from_message(incoming)
    result = await messenger.reply(context, reply.message)
    if not result.delivered:
        reply.delivery_failed()
        _log_delivery_failure(incoming, result, stage="initial")
        return
    reply.delivered()
    if reply.follow_up is None:
        return
    try:
        follow_up = await reply.follow_up()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception(
            "QQ Official deferred operation failed: account=%s kind=%s id=%s",
            incoming.conversation.account_id,
            incoming.conversation.kind,
            incoming.conversation.id,
        )
        follow_up = OutboundMessage.from_text(
            f"❌ 操作执行失败：{type(error).__name__}"
        )
    follow_up_result = await messenger.reply(context, follow_up)
    if not follow_up_result.delivered:
        _log_delivery_failure(incoming, follow_up_result, stage="follow_up")


def _log_delivery_failure(
    incoming: IncomingMessageRef,
    result: SendResult,
    *,
    stage: str,
) -> None:
    logger.warning(
        "QQ Official reply failed: stage=%s account=%s kind=%s id=%s "
        "code=%s message=%s trace_id=%s",
        stage,
        incoming.conversation.account_id,
        incoming.conversation.kind,
        incoming.conversation.id,
        getattr(result, "error_code", None),
        getattr(result, "error_message", None),
        getattr(result, "trace_id", None),
    )


def qq_official_event_is_supported(
    bot: QQOfficialBot,
    event: Event,
    router: PortableCommandRouter,
) -> bool:
    if not isinstance(event, (C2CMessageCreateEvent, GroupMessageCreateEvent)):
        return False
    if is_qq_official_reply_event(event):
        return False
    incoming = qq_official_incoming_message(event, account_id=bot.self_id)
    return router.recognizes(
        MessageInputContext(
            incoming,
            mentions_bot=qq_official_event_mentions_bot(event),
        )
    )


def qq_official_event_mentions_bot(event: QQMessageEvent) -> bool:
    """Distinguish an at-event from an authorized full-group event."""

    return isinstance(event, GroupAtMessageCreateEvent)
