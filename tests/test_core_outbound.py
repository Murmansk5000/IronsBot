from __future__ import annotations

from datetime import datetime

import pytest

from ironsbot.core.outbound import (
    COMMAND_REPLY_TEMPLATE,
    BinaryImagePart,
    DeliveryFailureKind,
    MentionPart,
    OutboundMessage,
    RemoteImagePart,
    ReplyContext,
    ReplyTemplate,
    SendResult,
    TextPart,
    format_outbound_message,
)
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)

PART_COUNT = 3


def test_outbound_message_accepts_text_and_image_parts() -> None:
    message = OutboundMessage(
        (
            TextPart("hello"),
            BinaryImagePart(b"png", "image/png", "card.png"),
            RemoteImagePart("https://example.test/card.png"),
        )
    )

    assert len(message.parts) == PART_COUNT


def test_outbound_message_builds_canonical_text_message() -> None:
    assert OutboundMessage.from_text("hello").parts == (TextPart("hello"),)


def test_outbound_message_rejects_empty_parts() -> None:
    with pytest.raises(ValueError, match="at least one part"):
        OutboundMessage(())


def test_outbound_template_preserves_structured_parts_and_text_formatting() -> None:
    image = BinaryImagePart(b"png", "image/png")

    message = format_outbound_message(
        "{command}第{index:02d}张：{image}（{random_text}）{{ok}}",
        command="图片",
        index=3,
        image=image,
        random_text="自选",
    )

    assert message.parts == (
        TextPart("图片第03张："),
        image,
        TextPart("（自选）{ok}"),
    )


def test_outbound_template_rejects_formatting_a_structured_part() -> None:
    with pytest.raises(ValueError, match="do not support"):
        format_outbound_message(
            "{image!s}",
            image=BinaryImagePart(b"png", "image/png"),
        )


def test_reply_context_and_send_result_require_complete_delivery_state() -> None:
    context = ReplyContext(
        ConversationRef(Platform.ONEBOT, "private", "123"),
        "message-1",
    )

    assert context.message_id == "message-1"
    assert SendResult(delivered=True, message_id="message-2").delivered
    assert not SendResult(delivered=False, error_code="unsupported").delivered


def test_send_result_rejects_incomplete_state() -> None:
    with pytest.raises(ValueError):
        SendResult(delivered=True)
    with pytest.raises(ValueError):
        SendResult(delivered=False)
    with pytest.raises(ValueError, match="failure kind"):
        SendResult(
            delivered=True,
            message_id="message",
            failure_kind=DeliveryFailureKind.RETRYABLE,
        )


def test_both_inbound_and_outbound_reject_naive_deadlines() -> None:
    conversation = ConversationRef(Platform.QQ_OFFICIAL, "private", "opaque:user")
    deadline = datetime(2026, 9, 5)  # noqa: DTZ001 - intentionally invalid input
    with pytest.raises(ValueError, match="timezone"):
        ReplyContext(conversation, "event", reply_deadline=deadline)
    with pytest.raises(ValueError, match="timezone"):
        IncomingMessageRef(
            Platform.QQ_OFFICIAL,
            ActorRef(Platform.QQ_OFFICIAL, "opaque:user"),
            conversation,
            "event",
            "query",
            reply_deadline=deadline,
        )


def test_reply_rejects_empty_sequence() -> None:
    with pytest.raises(ValueError, match="sequence"):
        ReplyContext(
            ConversationRef(Platform.QQ_OFFICIAL, "private", "opaque:user"),
            "event",
            sequence=" ",
        )


def test_command_reply_template_references_and_mentions_group_sender() -> None:
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-openid",
        account_id="app-id",
    )
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "member-openid",
        kind="member",
        scope_id=conversation.id,
        account_id=conversation.account_id,
    )
    incoming = IncomingMessageRef(
        Platform.QQ_OFFICIAL,
        actor,
        conversation,
        "message-id",
        "help",
    )

    prepared = COMMAND_REPLY_TEMPLATE.prepare(
        incoming,
        OutboundMessage.from_text("result"),
    )

    assert prepared.context == ReplyContext.from_message(incoming)
    assert prepared.message.parts == (
        MentionPart(actor),
        TextPart("\n"),
        TextPart("result"),
    )


def test_reply_template_can_disable_reference_and_sender_mention() -> None:
    conversation = ConversationRef(Platform.ONEBOT, "group", "456")
    incoming = IncomingMessageRef(
        Platform.ONEBOT,
        ActorRef(Platform.ONEBOT, "123", kind="member", scope_id="456"),
        conversation,
        "3",
        "help",
    )

    prepared = ReplyTemplate(
        include_reply=False,
        mention_sender=False,
    ).prepare(incoming, OutboundMessage.from_text("result"))

    assert prepared.context is None
    assert prepared.message == OutboundMessage.from_text("result")
