from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    OfficialUnionIdentity,
    Platform,
)


def test_platform_refs_keep_opaque_ids_as_nonempty_strings() -> None:
    actor = ActorRef(Platform.ONEBOT, " 123 ", account_id=" bot-1 ")
    conversation = ConversationRef(
        Platform.ONEBOT,
        "group",
        " 456 ",
        account_id=" bot-1 ",
    )

    assert actor.id == "123"
    assert actor.account_id == "bot-1"
    assert conversation.id == "456"
    assert conversation.account_id == "bot-1"


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
        platform=Platform.ONEBOT,
        actor=ActorRef(Platform.ONEBOT, "123"),
        conversation=ConversationRef(Platform.ONEBOT, "group", "456"),
        message_id="message-1",
        text="hello",
        direct_mentions=(ActorRef(Platform.ONEBOT, "789"),),
        reply_to_id="message-0",
    )

    assert message.message_id == "message-1"
    assert message.reply_to_id == "message-0"


def test_incoming_message_rejects_cross_platform_identity_mix() -> None:
    with pytest.raises(ValueError, match="platforms must match"):
        IncomingMessageRef(
            platform=Platform.ONEBOT,
            actor=ActorRef(Platform.ONEBOT, "123"),
            conversation=ConversationRef(Platform.QQ_OFFICIAL, "group", "456"),
            message_id="message-1",
            text="hello",
        )


def test_incoming_message_rejects_mismatched_declared_platform() -> None:
    with pytest.raises(ValueError, match="platforms must match"):
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=ActorRef(Platform.ONEBOT, "123"),
            conversation=ConversationRef(Platform.ONEBOT, "group", "456"),
            message_id="message-1",
            text="hello",
        )


def test_incoming_message_rejects_cross_account_identity_mix() -> None:
    with pytest.raises(ValueError, match="accounts must match"):
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=ActorRef(
                Platform.QQ_OFFICIAL,
                "user-open-id",
                account_id="bot-a",
            ),
            conversation=ConversationRef(
                Platform.QQ_OFFICIAL,
                "private",
                "user-open-id",
                account_id="bot-b",
            ),
            message_id="message-1",
            text="hello",
        )


def test_incoming_message_rejects_cross_account_direct_mention() -> None:
    with pytest.raises(ValueError, match="conversation accounts must match"):
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=ActorRef(
                Platform.QQ_OFFICIAL,
                "user-open-id",
                account_id="bot-a",
            ),
            conversation=ConversationRef(
                Platform.QQ_OFFICIAL,
                "group",
                "group-open-id",
                account_id="bot-a",
            ),
            message_id="message-1",
            text="hello",
            direct_mentions=(
                ActorRef(
                    Platform.QQ_OFFICIAL,
                    "mentioned-open-id",
                    account_id="bot-b",
                ),
            ),
        )


def test_incoming_message_preserves_sequence_and_timezone_aware_deadline() -> None:
    message = IncomingMessageRef(
        platform=Platform.QQ_OFFICIAL,
        actor=ActorRef(Platform.QQ_OFFICIAL, "user-open-id"),
        conversation=ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            "group-open-id",
        ),
        message_id="message-1",
        text="hello",
        sequence="sequence-1",
        reply_deadline=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
    )

    assert message.sequence == "sequence-1"
    assert message.reply_deadline is not None


def test_incoming_message_rejects_naive_reply_deadline() -> None:
    with pytest.raises(ValueError, match="timezone"):
        IncomingMessageRef(
            platform=Platform.ONEBOT,
            actor=ActorRef(Platform.ONEBOT, "1"),
            conversation=ConversationRef(Platform.ONEBOT, "private", "1"),
            message_id="message-1",
            text="hello",
            reply_deadline=datetime(
                2026,
                8,
                4,
                12,
                tzinfo=timezone.utc,
            ).replace(tzinfo=None),
        )


def test_official_union_identity_normalizes_optional_evidence() -> None:
    identity = OfficialUnionIdentity(" union-openid ", " union-account ")

    assert identity.union_openid == "union-openid"
    assert identity.union_user_account == "union-account"


def test_official_union_identity_rejects_empty_evidence() -> None:
    with pytest.raises(ValueError, match="at least one"):
        OfficialUnionIdentity(" ", None)


def test_onebot_message_rejects_official_union_identity() -> None:
    with pytest.raises(ValueError, match="QQ Official"):
        IncomingMessageRef(
            platform=Platform.ONEBOT,
            actor=ActorRef(Platform.ONEBOT, "1"),
            conversation=ConversationRef(Platform.ONEBOT, "private", "1"),
            message_id="message-1",
            text="hello",
            official_union_identity=OfficialUnionIdentity("union-openid"),
        )
