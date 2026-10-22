# SPDX-License-Identifier: MIT
"""OneBot self-message guard used by public menu ingress."""

from nonebot.adapters.onebot.v11 import MessageEvent


def is_self_message_event(event: MessageEvent) -> bool:
    return event.user_id == event.self_id
