# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageSegment, NoticeEvent, PokeNotifyEvent
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.rule import Rule

from ironsbot.services.help_hint import (
    can_send_group_help_hint,
    get_poke_reply,
    is_poke_at_bot,
)
from ironsbot.shared.help_hints import POKE_HELP_HINT_TEXT
from ironsbot.shared.matcher_priority import get_matcher_priority

if TYPE_CHECKING:
    from ironsbot.runtime.matchers import MatcherRegistry


async def _is_poke_at_bot(event: NoticeEvent) -> bool:
    if not isinstance(event, PokeNotifyEvent):
        return False
    return is_poke_at_bot(event)


async def handle_poke_help(matcher: Matcher, event: PokeNotifyEvent) -> None:
    if not can_send_group_help_hint(event.group_id):
        await matcher.finish()

    reply = (
        get_poke_reply(group_id=event.group_id, user_id=event.user_id)
        or POKE_HELP_HINT_TEXT
    )
    if event.group_id is None:
        await matcher.finish(reply)

    await matcher.finish(
        MessageSegment.at(event.user_id)
        + MessageSegment.text(f" {reply}")
    )


def install(registry: MatcherRegistry) -> None:
    matcher = registry.on_notice(
        rule=Rule(_is_poke_at_bot),
        priority=get_matcher_priority("help_hint", 0),
        block=True,
    )
    matcher.append_handler(handle_poke_help)
