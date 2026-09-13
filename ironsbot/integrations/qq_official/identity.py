# SPDX-License-Identifier: MIT
"""Translate QQ Official Bot events into opaque core identity values."""

from __future__ import annotations

from nonebot.adapters.qq.event import (
    C2CMessageCreateEvent,
    GroupMessageCreateEvent,
    QQMessageEvent,
)
from nonebot.adapters.qq.models import GroupMentionUser

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)


def qq_official_incoming_message(
    event: QQMessageEvent,
    *,
    account_id: str,
) -> IncomingMessageRef:
    if isinstance(event, GroupMessageCreateEvent):
        conversation_id = event.group_openid or event.group_id
        conversation = ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            conversation_id,
            account_id=account_id,
        )
        actor = ActorRef(
            Platform.QQ_OFFICIAL,
            event.author.member_openid,
            "member",
            conversation_id,
            account_id=account_id,
        )
        group_role = event.author.member_role
        direct_mentions = tuple(
            ActorRef(
                Platform.QQ_OFFICIAL,
                mention.member_openid,
                "member",
                conversation_id,
                account_id=account_id,
            )
            for mention in event.mentions or ()
            if isinstance(mention, GroupMentionUser)
            and not mention.is_you
            and not mention.bot
        )
    elif isinstance(event, C2CMessageCreateEvent):
        actor = ActorRef(
            Platform.QQ_OFFICIAL,
            event.author.user_openid,
            account_id=account_id,
        )
        conversation = ConversationRef(
            Platform.QQ_OFFICIAL,
            "private",
            actor.id,
            account_id=account_id,
        )
        group_role = None
        direct_mentions = ()
    else:
        msg = f"unsupported QQ Official message event: {type(event).__name__}"
        raise TypeError(msg)
    return IncomingMessageRef(
        platform=Platform.QQ_OFFICIAL,
        actor=actor,
        conversation=conversation,
        message_id=event.id,
        text=event.get_plaintext().strip(),
        direct_mentions=direct_mentions,
        group_role=group_role,
        sequence=event.msg_idx,
    )


def is_qq_official_reply_event(event: QQMessageEvent) -> bool:
    """Keep the application's global rule that quoted replies are ignored."""

    return event.reply is not None
