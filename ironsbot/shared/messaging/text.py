# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Message, MessageSegment

if TYPE_CHECKING:
    from collections.abc import Iterable

def render_text(text: str) -> str:
    return text.replace("\\n", "\n")


def build_message(
    text: str | Message | MessageSegment,
    at_user_ids: Iterable[int] = (),
) -> Message:
    message = Message()

    for user_id in dict.fromkeys(at_user_ids):
        message += MessageSegment.at(user_id)
        message += MessageSegment.text(" ")

    if isinstance(text, (Message, MessageSegment)):
        message += text
    else:
        message += MessageSegment.text(render_text(text))

    return message
