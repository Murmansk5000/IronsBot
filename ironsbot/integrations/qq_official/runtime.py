# SPDX-License-Identifier: MIT
"""Install the first production QQ Official passive-command runtime."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nonebot import on_message
from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves annotations
from nonebot.adapters.qq.event import (
    C2CMessageCreateEvent,
    GroupAtMessageCreateEvent,
    GroupMessageCreateEvent,
    QQMessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.rule import Rule

from ironsbot.core.message_input import MessageInputContext
from ironsbot.integrations.qq_official.identity import (
    is_qq_official_reply_event,
    qq_official_incoming_message,
)
from ironsbot.services.portable_commands import PortableCommandRouter  # noqa: TC001

if TYPE_CHECKING:
    from ironsbot.core.outbound import OutboundMessenger
    from ironsbot.core.platform import IncomingMessageRef
    from ironsbot.services.portable_reply import PortableReply

logger = logging.getLogger(__name__)


def install_qq_official_runtime(
    router: PortableCommandRouter,
    messenger: OutboundMessenger,
) -> None:
    """Register passive group/C2C handlers against nonebot-adapter-qq."""

    async def accepts(event: Event) -> bool:
        return qq_official_event_is_supported(event, router)

    async def handle(
        event: QQMessageEvent,
        matcher: Matcher,
    ) -> None:
        incoming = qq_official_incoming_message(event)
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

    result = await messenger.reply(ReplyContext.from_message(incoming), reply.message)
    if result.delivered:
        reply.delivered()
        return
    logger.warning(
        "QQ Official reply failed: kind=%s id=%s code=%s message=%s trace_id=%s",
        incoming.conversation.kind,
        incoming.conversation.id,
        result.error_code,
        result.error_message,
        result.trace_id,
    )


def qq_official_event_is_supported(
    event: Event,
    router: PortableCommandRouter,
) -> bool:
    if not isinstance(event, (C2CMessageCreateEvent, GroupMessageCreateEvent)):
        return False
    if is_qq_official_reply_event(event):
        return False
    incoming = qq_official_incoming_message(event)
    return router.recognizes(
        MessageInputContext(
            incoming,
            mentions_bot=qq_official_event_mentions_bot(event),
        )
    )


def qq_official_event_mentions_bot(event: QQMessageEvent) -> bool:
    """Distinguish an at-event from an authorized full-group event."""

    return isinstance(event, GroupAtMessageCreateEvent)
