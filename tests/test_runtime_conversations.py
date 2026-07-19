from ironsbot.runtime.conversations import (
    command_reply_check,
    event_conversation_session_id,
    is_self_message_event,
)
from tests.helpers.onebot_events import group_message_event, private_message_event


def _group_event(
    text: str = "帮助",
    *,
    user_id: int = 2,
    self_id: int = 1,
):
    return group_message_event(
        text,
        user_id=user_id,
        group_id=4,
        self_id=self_id,
    )


def _private_event(text: str = "帮助"):
    return private_message_event(
        text,
        user_id=2,
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


def test_is_self_message_event_detects_bot_message() -> None:
    assert is_self_message_event(_group_event(user_id=1, self_id=1))
    assert not is_self_message_event(_group_event(user_id=2, self_id=1))
