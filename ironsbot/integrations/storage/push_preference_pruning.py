# SPDX-License-Identifier: MIT
"""Prune obsolete push preferences without losing temporarily unroutable users."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar, cast

from ironsbot.core.platform import ConversationRef

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Container, Mapping
    from collections.abc import Set as AbstractSet

    from ironsbot.services.messaging.subscriptions import (
        PushPreferenceType,
        PushTimePreferenceIdentity,
    )

OwnerValues = Callable[[ConversationRef], tuple[str, str]]
T = TypeVar("T")


def _valid_by_owner(
    valid: Mapping[ConversationRef, AbstractSet[T]],
    owner_values: OwnerValues,
) -> dict[tuple[str, str], set[T]]:
    result: dict[tuple[str, str], set[T]] = {}
    for conversation, keys in valid.items():
        result.setdefault(owner_values(conversation), set()).update(keys)
    return result


def _preserve_private(
    *,
    kind: str,
    owner: tuple[str, str],
    valid_owners: Container[tuple[str, str]],
    preserve_unlisted_private: bool,
) -> bool:
    return preserve_unlisted_private and kind == "private" and owner not in valid_owners


def prune_unsubscriptions(
    con: sqlite3.Connection,
    valid: Mapping[ConversationRef, AbstractSet[str]],
    owner_values: OwnerValues,
    *,
    preserve_unlisted_private: bool,
) -> int:
    valid_by_owner = _valid_by_owner(valid, owner_values)
    rows = con.execute(
        """
        SELECT principal_kind, principal_id, subscription_key, conversation_kind
        FROM push_unsubscriptions
        """
    ).fetchall()
    deleted = 0
    for principal_kind, principal_id, key, kind in rows:
        owner = (str(principal_kind), str(principal_id))
        if _preserve_private(
            kind=kind,
            owner=owner,
            valid_owners=valid_by_owner,
            preserve_unlisted_private=preserve_unlisted_private,
        ) or str(key) in valid_by_owner.get(owner, set()):
            continue
        con.execute(
            """
            DELETE FROM push_unsubscriptions
            WHERE principal_kind = ? AND principal_id = ?
              AND subscription_key = ?
            """,
            (*owner, key),
        )
        deleted += 1
    return deleted


def prune_time_preferences(
    con: sqlite3.Connection,
    valid: Mapping[ConversationRef, AbstractSet[PushTimePreferenceIdentity]],
    owner_values: OwnerValues,
    *,
    preserve_unlisted_private: bool,
) -> int:
    valid_by_owner = _valid_by_owner(valid, owner_values)
    rows = con.execute(
        """
        SELECT principal_kind, principal_id, subscription_key,
               preference_type, conversation_kind
        FROM push_time_preferences
        """
    ).fetchall()
    deleted = 0
    for principal_kind, principal_id, key, preference_type, kind in rows:
        owner = (str(principal_kind), str(principal_id))
        if _preserve_private(
            kind=kind,
            owner=owner,
            valid_owners=valid_by_owner,
            preserve_unlisted_private=preserve_unlisted_private,
        ):
            continue
        identity = (str(key), cast("PushPreferenceType", preference_type))
        if preference_type in {
            "cron_time",
            "activity_lead_hours",
        } and identity in valid_by_owner.get(owner, set()):
            continue
        con.execute(
            """
            DELETE FROM push_time_preferences
            WHERE principal_kind = ? AND principal_id = ?
              AND subscription_key = ? AND preference_type = ?
            """,
            (*owner, key, preference_type),
        )
        deleted += 1
    return deleted
