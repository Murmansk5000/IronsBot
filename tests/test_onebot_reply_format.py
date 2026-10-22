from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ironsbot.core.outbound import (
    COMMAND_REPLY_TEMPLATE,
    BinaryImagePart,
    MentionPart,
    OutboundMessage,
    TextPart,
)
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.integrations.onebot.message_input import message_input_context
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from types import SimpleNamespace

pytest_plugins = ("tests.test_shared_onebot_ingress",)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["text", "newline", "literal", "image"])
async def test_actual_reply_uses_shared_text_and_media_format(
    runtime: SimpleNamespace, kind: str
) -> None:
    context = message_input_context(group_message_event(user_id=123, message_id=789))
    text = {
        "text": "result",
        "newline": "a\nb",
        "literal": "[CQ:image,file=https://example.test/image][CQ:at,qq=321]",
    }.get(kind, "caption")
    body = OutboundMessage(
        (BinaryImagePart(b"image", "image/png"), TextPart(text))
        if kind == "image"
        else (TextPart(text),)
    )
    result = await runtime.messenger.reply_from(runtime.bot, context, body)
    assert result.delivered
    (sent,) = runtime.sends
    message = sent["message"]
    assert message[0] == {"type": "reply", "data": {"id": "789"}}
    assert [part["type"] for part in message] == (
        ["reply", "image", "text"]
        if kind == "image"
        else ["reply", "at", "text", "text"]
    )
    assert message[-1]["data"]["text"] == text
    if kind != "image":
        assert message[1] == {"type": "at", "data": {"qq": "123"}}
        assert message[2] == {"type": "text", "data": {"text": "\n"}}


@pytest.mark.asyncio
async def test_actual_reply_does_not_duplicate_explicit_business_recipient(
    runtime: SimpleNamespace,
) -> None:
    context = message_input_context(group_message_event(user_id=123, message_id=789))
    body = OutboundMessage(
        (MentionPart(ActorRef(Platform.ONEBOT, "456")), TextPart("result"))
    )
    assert (await runtime.messenger.reply_from(runtime.bot, context, body)).delivered
    (sent,) = runtime.sends
    assert sent["message"] == [
        {"type": "reply", "data": {"id": "789"}},
        {"type": "at", "data": {"qq": "456"}},
        {"type": "text", "data": {"text": "result"}},
    ]


@pytest.mark.asyncio
async def test_actual_sender_accepts_already_prepared_public_message(
    runtime: SimpleNamespace,
) -> None:
    context = message_input_context(group_message_event(message_id=-10))
    prepared = COMMAND_REPLY_TEMPLATE.prepare(
        context.message, OutboundMessage.from_text("result")
    )
    assert (
        await runtime.messenger.reply_from(runtime.bot, context, prepared.message)
    ).delivered
    (sent,) = runtime.sends
    assert [part["type"] for part in sent["message"]] == ["reply", "at", "text", "text"]
    assert sent["message"][0] == {"type": "reply", "data": {"id": "-10"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("caption", [False, True])
@pytest.mark.parametrize("explicit_mention", [False, True])
async def test_actual_image_reply_references_sender_without_repeating_mention(
    runtime: SimpleNamespace, *, caption: bool, explicit_mention: bool
) -> None:
    context = message_input_context(group_message_event(user_id=123, message_id=-7))
    body = (BinaryImagePart(b"image", "image/png"),)
    if caption:
        body = (*body, TextPart("caption"))
    message = OutboundMessage(
        (MentionPart(context.message.actor), TextPart(" "), *body)
        if explicit_mention
        else body
    )
    assert (await runtime.messenger.reply_from(runtime.bot, context, message)).delivered
    (sent,) = runtime.sends
    assert sent["message"][0] == {"type": "reply", "data": {"id": "-7"}}
    assert [part["type"] for part in sent["message"]] == (
        ["reply", "image", "text"] if caption else ["reply", "image"]
    )


@pytest.mark.asyncio
async def test_actual_image_reply_keeps_other_business_recipient(
    runtime: SimpleNamespace,
) -> None:
    context = message_input_context(group_message_event(user_id=123, message_id=7))
    body = OutboundMessage(
        (
            MentionPart(context.message.actor),
            TextPart(" "),
            MentionPart(ActorRef(Platform.ONEBOT, "321")),
            TextPart(" "),
            BinaryImagePart(b"image", "image/png"),
        )
    )
    assert (await runtime.messenger.reply_from(runtime.bot, context, body)).delivered
    (sent,) = runtime.sends
    message = sent["message"]
    assert message[0] == {"type": "reply", "data": {"id": "7"}}
    assert [part["data"]["qq"] for part in message if part["type"] == "at"] == ["321"]
