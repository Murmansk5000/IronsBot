from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, PrivateMessageEvent

from ironsbot.shared.messaging.replies import event_sender_at_user_ids


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


def test_event_sender_at_user_ids_mentions_group_sender() -> None:
    assert event_sender_at_user_ids(_group_event()) == (2,)


def test_event_sender_at_user_ids_ignores_private_sender() -> None:
    assert event_sender_at_user_ids(_private_event()) == ()


def test_event_sender_at_user_ids_ignores_missing_event() -> None:
    assert event_sender_at_user_ids(None) == ()
