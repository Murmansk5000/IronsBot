# SPDX-License-Identifier: MIT
from __future__ import annotations

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent


def event_sender_at_user_ids(
    event: MessageEvent | None,
    *,
    mention_sender: bool = False,
) -> tuple[int, ...]:
    del mention_sender

    if not isinstance(event, GroupMessageEvent):
        return ()

    return (event.user_id,)
