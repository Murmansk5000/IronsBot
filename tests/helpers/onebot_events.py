from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

from nonebot.adapters.onebot.v11 import (
    GroupIncreaseNoticeEvent,
    GroupMessageEvent,
    Message,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.adapters.onebot.v11.event import Reply, Sender

from ironsbot.integrations.onebot.ingress_facts import (
    OneBotMessageOrigin,
    onebot_admission_input,
)
from ironsbot.integrations.onebot.message_input import message_input_facts
from ironsbot.integrations.onebot.self_commands import (
    SelfCommandAdapter,
    SentGroupMessageEvent,
)

if TYPE_CHECKING:
    from ironsbot.core.own_commands import OwnAccountInput

GroupMemberRole = Literal["owner", "admin", "member"]
SenderInput = Sender | Mapping[str, Any] | None


def own_account_input(event: SentGroupMessageEvent) -> OwnAccountInput:
    incoming = onebot_admission_input(
        message_input_facts(event), OneBotMessageOrigin.SENT_GROUP
    )
    assert incoming.own_input is not None
    return incoming.own_input


def _sender_model(sender: SenderInput, *, user_id: int) -> Sender:
    if isinstance(sender, Sender):
        return sender
    if sender is None:
        return Sender(user_id=user_id)
    return Sender(user_id=user_id, **sender)


def group_message_event(  # noqa: PLR0913
    text: str = "hello",
    *,
    user_id: int = 123,
    group_id: int = 456,
    self_id: int = 1,
    message_id: int = 3,
    sender: SenderInput = None,
    message: Message | None = None,
    original_message: Message | None = None,
    raw_message: str | None = None,
    to_me: bool = False,
    reply_sender_user_id: int | None = None,
    reply_message_id: int | None = None,
) -> GroupMessageEvent:
    event_message = message or Message(text)
    event = GroupMessageEvent(
        time=0,
        self_id=self_id,
        post_type="message",
        sub_type="normal",
        user_id=user_id,
        message_type="group",
        message_id=message_id,
        message=event_message,
        original_message=original_message or event_message,
        raw_message=text if raw_message is None else raw_message,
        font=0,
        group_id=group_id,
        sender=_sender_model(sender, user_id=user_id),
        to_me=to_me,
    )
    if reply_sender_user_id is not None:
        resolved_reply_message_id = (
            message_id - 1 if reply_message_id is None else reply_message_id
        )
        event.reply = Reply(
            time=0,
            message_type="group",
            message_id=resolved_reply_message_id,
            real_id=resolved_reply_message_id,
            sender=Sender(user_id=reply_sender_user_id),
            message=Message("reply"),
        )
    if original_message is not None:
        event.original_message = original_message
    return event


def self_command_event(text: str, message_id: int = -3) -> SentGroupMessageEvent:
    data = group_message_event(text, user_id=1, message_id=message_id).model_dump()
    data["post_type"] = "message_sent"
    event = SelfCommandAdapter.json_to_event(data)
    assert isinstance(event, SentGroupMessageEvent)
    return event


def group_at_message_event(  # noqa: PLR0913
    *,
    self_id: int = 1,
    user_id: int = 123,
    group_id: int = 456,
    message_id: int = 3,
    reply_sender_user_id: int | None = None,
    reply_message_id: int | None = None,
) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=0,
        self_id=self_id,
        post_type="message",
        sub_type="normal",
        user_id=user_id,
        message_type="group",
        message_id=message_id,
        message=Message(MessageSegment.at(self_id)),
        original_message=Message(MessageSegment.at(self_id)),
        raw_message=f"[CQ:at,qq={self_id}]",
        font=0,
        group_id=group_id,
        sender=Sender(user_id=user_id),
        reply=(
            Reply(
                time=0,
                message_type="group",
                message_id=(
                    message_id - 1 if reply_message_id is None else reply_message_id
                ),
                real_id=(
                    message_id - 1 if reply_message_id is None else reply_message_id
                ),
                sender=Sender(user_id=reply_sender_user_id),
                message=Message("reply"),
            )
            if reply_sender_user_id is not None
            else None
        ),
    )


def group_member_message_event(  # noqa: PLR0913
    text: str = "hello",
    *,
    role: GroupMemberRole = "member",
    user_id: int = 123,
    group_id: int = 456,
    self_id: int = 1,
    message_id: int = 3,
) -> GroupMessageEvent:
    return group_message_event(
        text,
        user_id=user_id,
        group_id=group_id,
        self_id=self_id,
        message_id=message_id,
        sender=Sender(user_id=user_id, role=role),
    )


def group_admin_message_event(
    text: str = "hello",
    *,
    user_id: int = 123,
    group_id: int = 456,
    self_id: int = 1,
    message_id: int = 3,
) -> GroupMessageEvent:
    return group_member_message_event(
        text,
        role="admin",
        user_id=user_id,
        group_id=group_id,
        self_id=self_id,
        message_id=message_id,
    )


def group_owner_message_event(
    text: str = "hello",
    *,
    user_id: int = 123,
    group_id: int = 456,
    self_id: int = 1,
    message_id: int = 3,
) -> GroupMessageEvent:
    return group_member_message_event(
        text,
        role="owner",
        user_id=user_id,
        group_id=group_id,
        self_id=self_id,
        message_id=message_id,
    )


def private_message_event(
    text: str = "hello",
    *,
    user_id: int = 123,
    self_id: int = 1,
    message_id: int = 3,
    sender: SenderInput = None,
) -> PrivateMessageEvent:
    return PrivateMessageEvent(
        time=0,
        self_id=self_id,
        post_type="message",
        sub_type="friend",
        user_id=user_id,
        message_type="private",
        message_id=message_id,
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        sender=_sender_model(sender, user_id=user_id),
    )


def group_increase_notice_event(
    *,
    user_id: int = 123,
    group_id: int = 456,
    operator_id: int = 789,
    self_id: int = 1,
    sub_type: str = "approve",
) -> GroupIncreaseNoticeEvent:
    return GroupIncreaseNoticeEvent(
        time=0,
        self_id=self_id,
        post_type="notice",
        notice_type="group_increase",
        sub_type=sub_type,
        group_id=group_id,
        user_id=user_id,
        operator_id=operator_id,
    )
