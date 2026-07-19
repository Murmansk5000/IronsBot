from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.runtime.onebot_context import mentions_bot
from tests.helpers.onebot_events import group_at_message_event, group_message_event

BOT_ID = 100
OTHER_USER_ID = 200


def test_mentions_bot_matches_direct_at() -> None:
    event = group_at_message_event(self_id=BOT_ID)

    assert mentions_bot(event)


def test_mentions_bot_ignores_direct_at_when_message_is_reply() -> None:
    event = group_at_message_event(
        self_id=BOT_ID,
        reply_sender_user_id=OTHER_USER_ID,
    )

    assert not mentions_bot(event)


def test_mentions_bot_ignores_foreign_at() -> None:
    event = group_message_event(
        self_id=BOT_ID,
        message=Message(MessageSegment.at(OTHER_USER_ID)),
    )

    assert not mentions_bot(event)


def test_mentions_bot_does_not_treat_reply_as_mention() -> None:
    event = group_message_event(
        self_id=BOT_ID,
        reply_sender_user_id=BOT_ID,
    )

    assert not mentions_bot(event)


def test_mentions_bot_treats_stripped_to_me_as_mention() -> None:
    event = group_message_event("", self_id=BOT_ID, to_me=True)

    assert mentions_bot(event)


def test_mentions_bot_does_not_treat_reply_only_to_me_as_mention() -> None:
    event = group_message_event(
        "",
        self_id=BOT_ID,
        to_me=True,
        reply_sender_user_id=BOT_ID,
    )

    assert not mentions_bot(event)


def test_mentions_bot_matches_original_message_after_preprocessing() -> None:
    event = group_message_event(
        "",
        self_id=BOT_ID,
        original_message=Message(MessageSegment.at(BOT_ID)),
    )

    assert mentions_bot(event)


def test_mentions_bot_ignores_original_message_at_when_message_is_reply() -> None:
    event = group_message_event(
        "",
        self_id=BOT_ID,
        original_message=Message(MessageSegment.at(BOT_ID)),
        reply_sender_user_id=OTHER_USER_ID,
    )

    assert not mentions_bot(event)


def test_mentions_bot_matches_raw_cq_at_after_preprocessing() -> None:
    event = group_message_event("", self_id=BOT_ID, raw_message="[CQ:at,qq=100] ")

    assert mentions_bot(event)


def test_mentions_bot_ignores_raw_cq_at_when_message_is_reply() -> None:
    event = group_message_event(
        "",
        self_id=BOT_ID,
        raw_message="[CQ:at,qq=100] ",
        reply_sender_user_id=OTHER_USER_ID,
    )

    assert not mentions_bot(event)
