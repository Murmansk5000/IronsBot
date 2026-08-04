# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
    PlatformIdentityStorageError,
)


def test_actor_identity_columns_round_trip_a_scoped_member() -> None:
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "member-open-id",
        kind="member",
        scope_id="group-open-id",
    )

    stored = ActorIdentityColumns.from_actor(actor)

    assert stored.values() == (
        "qq_official",
        "member",
        "member-open-id",
        "group-open-id",
    )
    assert stored.to_actor() == actor


def test_actor_identity_columns_round_trip_unscoped_onebot_user() -> None:
    actor = ActorRef(Platform.ONEBOT, "123456")

    stored = ActorIdentityColumns.from_actor(actor)

    assert stored.scope_id == ""
    assert stored.to_actor() == actor


def test_conversation_identity_columns_round_trip() -> None:
    conversation = ConversationRef(Platform.QQ_OFFICIAL, "channel", "channel-id")

    stored = ConversationIdentityColumns.from_conversation(conversation)

    assert stored.values() == ("qq_official", "channel", "channel-id")
    assert stored.to_conversation() == conversation


@pytest.mark.parametrize(
    ("columns", "message"),
    (
        (
            ActorIdentityColumns("onebot", "member", "123", ""),
            "actor identity",
        ),
        (
            ConversationIdentityColumns("onebot", "unsupported", "123"),
            "conversation identity",
        ),
    ),
)
def test_invalid_stored_identity_is_rejected(
    columns: ActorIdentityColumns | ConversationIdentityColumns,
    message: str,
) -> None:
    with pytest.raises(PlatformIdentityStorageError, match=message):
        if isinstance(columns, ActorIdentityColumns):
            columns.to_actor()
        else:
            columns.to_conversation()
