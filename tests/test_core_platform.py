from __future__ import annotations

from datetime import datetime, timezone

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


def test_member_actor_requires_scope_and_preserves_platform_identity() -> None:
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "member-open-id",
        kind="member",
        scope_id="group-open-id",
    )

    assert actor.platform is Platform.QQ_OFFICIAL
    assert actor.kind == "member"
    assert actor.scope_id == "group-open-id"


@pytest.mark.parametrize(
    ("kind", "scope_id", "message"),
    (
        ("member", None, "scope"),
        ("user", "group-open-id", "scope"),
        ("invalid", None, "actor kind"),
    ),
)
def test_actor_ref_rejects_invalid_scope_shapes(
    kind: str,
    scope_id: str | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ActorRef(
            Platform.QQ_OFFICIAL,
            "open-id",
            kind=kind,  # type: ignore[arg-type]
            scope_id=scope_id,
        )


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


def test_incoming_message_preserves_sequence_and_timezone_aware_deadline() -> None:
    message = IncomingMessageRef(
        id="message-1",
        actor=ActorRef(Platform.QQ_OFFICIAL, "user-open-id"),
        conversation=ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            "group-open-id",
        ),
        text="hello",
        sequence="sequence-1",
        reply_deadline=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
    )

    assert message.sequence == "sequence-1"
    assert message.reply_deadline is not None


def test_incoming_message_rejects_naive_reply_deadline() -> None:
    with pytest.raises(ValueError, match="timezone"):
        IncomingMessageRef(
            id="message-1",
            actor=ActorRef(Platform.ONEBOT, "1"),
            conversation=ConversationRef(Platform.ONEBOT, "private", "1"),
            text="hello",
            reply_deadline=datetime(
                2026,
                8,
                4,
                12,
                tzinfo=timezone.utc,
            ).replace(tzinfo=None),
        )
