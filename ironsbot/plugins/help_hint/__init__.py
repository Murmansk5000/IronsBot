# SPDX-License-Identifier: MIT
from __future__ import annotations

from nonebot import on_notice
from nonebot.adapters.onebot.v11 import MessageSegment, NoticeEvent, PokeNotifyEvent
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.rule import Rule

from ironsbot.services.help_hint import can_send_group_help_hint, is_poke_at_bot
from ironsbot.shared.help_hints import POKE_HELP_HINT_TEXT


async def _is_poke_at_bot(event: NoticeEvent) -> bool:
    if not isinstance(event, PokeNotifyEvent):
        return False
    return is_poke_at_bot(event)


poke_help_matcher = on_notice(
    rule=Rule(_is_poke_at_bot),
    priority=0,
    block=True,
)


@poke_help_matcher.handle()
async def handle_poke_help(matcher: Matcher, event: PokeNotifyEvent) -> None:
    if not can_send_group_help_hint(event.group_id):
        await matcher.finish()

    if event.group_id is None:
        await matcher.finish(POKE_HELP_HINT_TEXT)

    await matcher.finish(
        MessageSegment.at(event.user_id)
        + MessageSegment.text(f" {POKE_HELP_HINT_TEXT}")
    )
