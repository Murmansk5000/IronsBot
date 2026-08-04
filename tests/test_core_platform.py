from __future__ import annotations

import pytest

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)


def test_platform_refs_keep_opaque_ids_as_nonempty_strings() -> None:
    actor = ActorRef(Platform.ONEBOT, " 123 ")
    conversation = ConversationRef(Platform.ONEBOT, "group", " 456 ")

    assert actor.id == "123"
    assert conversation.id == "456"


@pytest.mark.parametrize("value", ("", "   "))
def test_platform_refs_reject_empty_ids(value: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        ActorRef(Platform.ONEBOT, value)


def test_incoming_message_requires_one_platform_for_all_identity_refs() -> None:
    message = IncomingMessageRef(
        id="message-1",
        actor=ActorRef(Platform.ONEBOT, "123"),
        conversation=ConversationRef(Platform.ONEBOT, "group", "456"),
        text="hello",
        direct_mentions=(ActorRef(Platform.ONEBOT, "789"),),
        reply_to_id="message-0",
    )

    assert message.reply_to_id == "message-0"


def test_incoming_message_rejects_cross_platform_identity_mix() -> None:
    with pytest.raises(ValueError, match="platforms must match"):
        IncomingMessageRef(
            id="message-1",
            actor=ActorRef(Platform.ONEBOT, "123"),
            conversation=ConversationRef(Platform.QQ_OFFICIAL, "group", "456"),
            text="hello",
        )
