# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable

from nonebot.adapters.onebot.v11 import MessageEvent

from .text import command_text_matches

EventReplyCheck = Callable[[MessageEvent], bool]


def event_conversation_session_id(namespace: str, event: MessageEvent) -> str:
    group_id = getattr(event, "group_id", None)
    target = f"group:{group_id}" if group_id is not None else "private"
    return f"{namespace}:{target}:user:{event.user_id}"


def command_reply_check(commands: tuple[str, ...] | list[str]) -> EventReplyCheck:
    def _check(event: MessageEvent) -> bool:
        return command_text_matches(event.get_plaintext(), commands)

    return _check
