# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent

from ironsbot.services.seer.query_help import seer_query_help_message
from ironsbot.shared.messaging import finish_event_reply

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.matcher import Matcher


async def finish_query_help(
    matcher: Matcher,
    event: Event,
    kind: str,
) -> None:
    message = seer_query_help_message(kind)
    if isinstance(event, MessageEvent):
        await finish_event_reply(matcher, event, message)
    await matcher.finish(message)
