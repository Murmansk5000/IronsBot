from __future__ import annotations

from nonebot.adapters.onebot.v11 import (
    GroupIncreaseNoticeEvent,
    GroupMessageEvent,
    Message,
    PrivateMessageEvent,
)


def group_message_event(  # noqa: PLR0913
    text: str = "hello",
    *,
    user_id: int = 123,
    group_id: int = 456,
    self_id: int = 1,
    message_id: int = 3,
    sender: dict[str, object] | None = None,
) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=0,
        self_id=self_id,
        post_type="message",
        sub_type="normal",
        user_id=user_id,
        message_type="group",
        message_id=message_id,
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        group_id=group_id,
        sender=sender or {},
    )


def private_message_event(
    text: str = "hello",
    *,
    user_id: int = 123,
    self_id: int = 1,
    message_id: int = 3,
    sender: dict[str, object] | None = None,
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
        sender=sender or {},
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
