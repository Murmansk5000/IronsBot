# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import MessageEvent

from ironsbot.shared.messaging import finish_event_reply

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.shared.messaging import ReplyMessage


async def finish_query_reply(
    matcher: Any,
    event: Event,
    message: ReplyMessage,
) -> None:
    if isinstance(event, MessageEvent):
        await finish_event_reply(matcher, event, message)
        return

    await matcher.finish(message)


__all__ = ["finish_query_reply"]
