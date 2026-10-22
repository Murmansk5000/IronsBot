from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.message_input import MessageInputKind
from tests.helpers.onebot_events import group_at_message_event, group_message_event
from tests.helpers.onebot_inputs import message_input_context

BOT_ID = 100
OTHER_USER_ID = 200


def test_addressed_input_kind_matches_direct_at() -> None:
    event = group_at_message_event(self_id=BOT_ID)

    assert message_input_context(event).kind is MessageInputKind.BOT_MENTION


def test_addressed_input_kind_ignores_direct_at_when_message_is_reply() -> None:
    event = group_at_message_event(
        self_id=BOT_ID,
        reply_sender_user_id=OTHER_USER_ID,
    )

    assert message_input_context(event).kind is not MessageInputKind.BOT_MENTION


def test_addressed_input_kind_ignores_foreign_at() -> None:
    event = group_message_event(
        self_id=BOT_ID,
        message=Message(MessageSegment.at(OTHER_USER_ID)),
    )

    assert message_input_context(event).kind is not MessageInputKind.BOT_MENTION


def test_addressed_input_kind_does_not_treat_reply_as_mention() -> None:
    event = group_message_event(
        self_id=BOT_ID,
        reply_sender_user_id=BOT_ID,
    )

    assert message_input_context(event).kind is not MessageInputKind.BOT_MENTION


def test_addressed_input_kind_treats_stripped_to_me_as_mention() -> None:
    event = group_message_event("", self_id=BOT_ID, to_me=True)

    assert message_input_context(event).kind is MessageInputKind.BOT_MENTION


def test_addressed_input_kind_does_not_treat_reply_only_to_me_as_mention() -> None:
    event = group_message_event(
        "",
        self_id=BOT_ID,
        to_me=True,
        reply_sender_user_id=BOT_ID,
    )

    assert message_input_context(event).kind is not MessageInputKind.BOT_MENTION


def test_addressed_input_kind_matches_original_message_after_preprocessing() -> None:
    event = group_message_event(
        "",
        self_id=BOT_ID,
        original_message=Message(MessageSegment.at(BOT_ID)),
    )

    assert message_input_context(event).kind is MessageInputKind.BOT_MENTION


def test_addressed_kind_ignores_original_at_in_reply() -> None:
    event = group_message_event(
        "",
        self_id=BOT_ID,
        original_message=Message(MessageSegment.at(BOT_ID)),
        reply_sender_user_id=OTHER_USER_ID,
    )

    assert message_input_context(event).kind is not MessageInputKind.BOT_MENTION


def test_addressed_input_kind_matches_raw_cq_at_after_preprocessing() -> None:
    event = group_message_event("", self_id=BOT_ID, raw_message="[CQ:at,qq=100] ")

    assert message_input_context(event).kind is MessageInputKind.BOT_MENTION


def test_addressed_input_kind_ignores_raw_cq_at_when_message_is_reply() -> None:
    event = group_message_event(
        "",
        self_id=BOT_ID,
        raw_message="[CQ:at,qq=100] ",
        reply_sender_user_id=OTHER_USER_ID,
    )

    assert message_input_context(event).kind is not MessageInputKind.BOT_MENTION
