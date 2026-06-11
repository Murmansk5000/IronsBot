from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, PrivateMessageEvent

from ironsbot.shared.messaging.conversations import (
    command_reply_check,
    event_conversation_session_id,
)


def _group_event(text: str = "帮助") -> GroupMessageEvent:
    return GroupMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=2,
        message_type="group",
        message_id=3,
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        group_id=4,
        sender={},
    )


def _private_event(text: str = "帮助") -> PrivateMessageEvent:
    return PrivateMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="friend",
        user_id=2,
        message_type="private",
        message_id=3,
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        sender={},
    )


def test_event_conversation_session_id_includes_group_context() -> None:
    assert (
        event_conversation_session_id("menu", _group_event())
        == "menu:group:4:user:2"
    )


def test_event_conversation_session_id_uses_private_context() -> None:
    assert (
        event_conversation_session_id("menu", _private_event())
        == "menu:private:user:2"
    )


def test_command_reply_check_matches_normalized_commands() -> None:
    check = command_reply_check(("收集",))

    assert check(_group_event(" 收 集 "))
    assert not check(_group_event("巅峰"))
