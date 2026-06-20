from nonebot.adapters.onebot.v11 import Message
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment

from ironsbot.plugins.admin_priority import wait_for_superuser_priority
from ironsbot.shared.messaging import (
    ReplyMessage,
    configure_reply_delivery_policy,
    configure_sender_message_limiter,
)

from .reply_limits import limit_message_by_reply_lines

_policy_state = {"registered": False}


def _limit_reply_message(
    message: ReplyMessage,
    event: MessageEvent | None,
    group_id: int | None,
) -> str | Message | MessageSegment:
    return limit_message_by_reply_lines(
        message,
        event=event,
        group_id=group_id,
    )


def _limit_broadcast_message(
    message: str | Message,
    group_id: int | None,
) -> str | Message:
    return limit_message_by_reply_lines(message, group_id=group_id)


def setup_messaging_delivery_policies() -> None:
    if _policy_state["registered"]:
        return

    configure_reply_delivery_policy(
        before_send=wait_for_superuser_priority,
        message_limiter=_limit_reply_message,
    )
    configure_sender_message_limiter(_limit_broadcast_message)
    _policy_state["registered"] = True
