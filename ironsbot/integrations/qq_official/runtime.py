# SPDX-License-Identifier: MIT
"""Install the first production QQ Official passive-command runtime."""

from __future__ import annotations

import logging

from nonebot import on_message
from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves annotations
from nonebot.adapters.qq import Bot as QQOfficialBot  # noqa: TC002
from nonebot.adapters.qq.event import (
    C2CMessageCreateEvent,
    GroupMessageCreateEvent,
    QQMessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.rule import Rule

from ironsbot.integrations.qq_official.identity import (
    is_qq_official_reply_event,
    qq_official_incoming_message,
)
from ironsbot.integrations.qq_official.message_rendering import (
    render_qq_official_outbound_message,
)
from ironsbot.services.portable_commands import PortableCommandRouter  # noqa: TC001

logger = logging.getLogger(__name__)


def install_qq_official_runtime(router: PortableCommandRouter) -> None:
    """Register passive group/C2C handlers against nonebot-adapter-qq."""

    async def accepts(event: Event) -> bool:
        return qq_official_event_is_supported(event, router)

    async def handle(
        bot: QQOfficialBot,
        event: QQMessageEvent,
        matcher: Matcher,
    ) -> None:
        incoming = qq_official_incoming_message(event)
        reply = await router.dispatch(
            incoming.text,
            actor=incoming.actor,
            conversation=incoming.conversation,
        )
        if reply is None:
            return
        rendered = render_qq_official_outbound_message(
            reply,
            conversation=incoming.conversation,
        )
        await bot.send(event, rendered)
        matcher.stop_propagation()

    matcher = on_message(
        rule=Rule(accepts),
        priority=10,
        block=True,
    )
    matcher.append_handler(handle)
    logger.info("QQ Official passive-command runtime installed")


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
        incoming.text,
        actor=incoming.actor,
        conversation=incoming.conversation,
    )
