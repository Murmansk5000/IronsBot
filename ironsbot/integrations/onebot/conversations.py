# SPDX-License-Identifier: MIT
"""OneBot self-message guard used by public menu ingress."""

from nonebot.adapters.onebot.v11 import MessageEvent

from ironsbot.integrations.onebot.self_commands import is_unaccepted_self_message


def is_self_message_event(event: MessageEvent) -> bool:
    return is_unaccepted_self_message(event)
