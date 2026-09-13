# SPDX-License-Identifier: MIT
"""Translate QQ Official Bot events into opaque core identity values."""

from __future__ import annotations

from nonebot.adapters.qq.event import (
    C2CMessageCreateEvent,
    GroupMessageCreateEvent,
    QQMessageEvent,
)

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)


def qq_official_incoming_message(event: QQMessageEvent) -> IncomingMessageRef:
    if isinstance(event, GroupMessageCreateEvent):
        conversation_id = event.group_openid or event.group_id
        conversation = ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            conversation_id,
        )
        actor = ActorRef(
            Platform.QQ_OFFICIAL,
            event.author.member_openid,
            "member",
            conversation_id,
        )
        group_role = event.author.member_role
    elif isinstance(event, C2CMessageCreateEvent):
        actor = ActorRef(Platform.QQ_OFFICIAL, event.author.user_openid)
        conversation = ConversationRef(Platform.QQ_OFFICIAL, "private", actor.id)
        group_role = None
    else:
        msg = f"unsupported QQ Official message event: {type(event).__name__}"
        raise TypeError(msg)
    return IncomingMessageRef(
        platform=Platform.QQ_OFFICIAL,
        actor=actor,
        conversation=conversation,
        message_id=event.id,
        text=event.get_plaintext().strip(),
        group_role=group_role,
        sequence=event.msg_idx,
    )


def is_qq_official_reply_event(event: QQMessageEvent) -> bool:
    """Keep the application's global rule that quoted replies are ignored."""

    return event.reply is not None
