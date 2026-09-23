import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.commands import (
    command_text_matches,
    normalize_command_text,
    strip_command_prefix,
)
from ironsbot.integrations.onebot.replies import (
    build_event_reply_message,
    build_message,
    render_text,
)
from tests.helpers.onebot_events import group_message_event


def test_normalize_command_text_removes_whitespace_and_lowercases() -> None:
    assert normalize_command_text(" X R Y M ") == "xrym"


def test_strip_command_prefix_uses_slash_by_default() -> None:
    assert strip_command_prefix("/更新数据") == "更新数据"
    assert strip_command_prefix("更新数据") is None


def test_command_text_matches_normalized_commands() -> None:
    assert command_text_matches(" X R Y M ", ["xrym"])
    assert not command_text_matches("xrym2", ["xrym"])


def test_render_text_expands_escaped_newlines() -> None:
    assert render_text("a\\nb") == "a\nb"


def test_build_message_renders_mentions_and_text() -> None:
    message = build_message("a\\nb", at_user_ids=[1, 1, 2])

    assert [segment.type for segment in message] == ["at", "text", "at", "text", "text"]
    assert message[0].data["qq"] == "1"
    assert message[2].data["qq"] == "2"
    assert message[-1].data["text"] == "a\nb"


def test_event_reply_uses_shared_reference_mention_and_newline_template() -> None:
    event = group_message_event(user_id=123, group_id=456, message_id=789)

    message = build_event_reply_message(event, "result")

    assert [segment.type for segment in message] == ["reply", "at", "text", "text"]
    assert message[0].data["id"] == "789"
    assert message[1].data["qq"] == "123"
    assert message[2].data["text"] == "\n"
    assert message[3].data["text"] == "result"


def test_event_reply_does_not_duplicate_explicit_mention() -> None:
    event = group_message_event(user_id=123, group_id=456, message_id=789)
    explicit = Message((MessageSegment.at(456), MessageSegment.text("result")))

    message = build_event_reply_message(event, explicit)

    assert [segment.type for segment in message] == ["reply", "at", "text"]
    assert message[1].data["qq"] == "456"


def test_event_reply_is_idempotent_for_already_prepared_message() -> None:
    event = group_message_event(message_id=-10)
    prepared = build_event_reply_message(event, "result")
    assert build_event_reply_message(event, prepared) == prepared


@pytest.mark.parametrize("caption", [False, True])
@pytest.mark.parametrize("explicit_mention", [False, True])
def test_image_reply_uses_reference_instead_of_sender_mention(
    *, caption: bool, explicit_mention: bool
) -> None:
    event = group_message_event(user_id=123, message_id=-7)
    body = Message(MessageSegment.image(b"image"))
    if caption:
        body += MessageSegment.text("caption")
    source = build_message(body, at_user_ids=[123]) if explicit_mention else body

    reply = build_event_reply_message(event, source)

    assert reply == MessageSegment.reply(-7) + body
    assert build_event_reply_message(event, reply) == reply


def test_image_reply_keeps_business_recipient_but_removes_sender_prefix() -> None:
    event = group_message_event(user_id=123, message_id=7)
    body = build_message(MessageSegment.image(b"image"), at_user_ids=[123, 321])

    reply = build_event_reply_message(event, body)

    assert reply[0] == MessageSegment.reply(7)
    assert [part.data["qq"] for part in reply if part.type == "at"] == ["321"]


def test_plain_text_cq_syntax_cannot_turn_into_an_image_or_mention() -> None:
    event = group_message_event(message_id=7)
    text = "[CQ:image,file=https://example.test/image][CQ:at,qq=321]"

    reply = build_event_reply_message(event, text)

    assert [part.type for part in reply] == ["reply", "at", "text", "text"]
    assert reply[-1].data["text"] == text
