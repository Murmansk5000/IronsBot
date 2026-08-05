# SPDX-License-Identifier: MIT
"""Conversation-scoped scheduled-push preferences."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ironsbot.core.platform import ConversationKind, ConversationRef, Platform
from ironsbot.integrations.storage.platform_identity import (
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration
from ironsbot.services.messaging.subscriptions import (
    PushPreferencePruneResult,
    PushPreferenceType,
    PushTimePreference,
    PushTimePreferenceIdentity,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Mapping
    from collections.abc import Set as AbstractSet
    from contextlib import AbstractContextManager


PUSH_SUBSCRIPTION_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS push_unsubscriptions (
        conversation_platform TEXT NOT NULL,
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        subscription_key TEXT NOT NULL,
        feature TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (
            conversation_platform, conversation_kind, conversation_id,
            subscription_key
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_push_unsubscriptions_lookup
    ON push_unsubscriptions (
        conversation_platform, conversation_kind, subscription_key,
        conversation_id
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS push_time_preferences (
        conversation_platform TEXT NOT NULL,
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        subscription_key TEXT NOT NULL,
        preference_type TEXT NOT NULL,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (
            conversation_platform, conversation_kind, conversation_id,
            subscription_key, preference_type
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_push_time_preferences_lookup
    ON push_time_preferences (
        conversation_platform, conversation_kind, subscription_key,
        preference_type, conversation_id
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS push_daily_hints (
        conversation_platform TEXT NOT NULL,
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        hint_key TEXT NOT NULL,
        delivered_on TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (
            conversation_platform, conversation_kind, conversation_id, hint_key
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_push_daily_hints_lookup
    ON push_daily_hints (
        conversation_platform, conversation_kind, hint_key, delivered_on
    )
    """,
)
PUSH_SUBSCRIPTION_MIGRATIONS = (
    SqliteMigration(1, PUSH_SUBSCRIPTION_SCHEMA),
)
MIGRATION_NAMESPACE = "push_subscriptions"


class PushUnsubscribeStore:
    """Persist push state by opaque conversation identity only."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._database = SqliteDatabase(
            self.path,
            migrations=PUSH_SUBSCRIPTION_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    def unsubscribed_keys(self, conversation: ConversationRef) -> set[str]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT subscription_key FROM push_unsubscriptions
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ?
                """,
                _conversation_values(conversation),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def is_unsubscribed(
        self,
        conversation: ConversationRef,
        subscription_key: str,
    ) -> bool:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT 1 FROM push_unsubscriptions
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND subscription_key = ?
                """,
                (*_conversation_values(conversation), subscription_key),
            ).fetchone()
        return row is not None

    def unsubscribe(
        self,
        conversation: ConversationRef,
        subscription_key: str,
        feature: str,
    ) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO push_unsubscriptions (
                    conversation_platform, conversation_kind, conversation_id,
                    subscription_key, feature, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    *_conversation_values(conversation),
                    subscription_key,
                    feature,
                    _now(),
                ),
            )

    def restore(
        self,
        conversation: ConversationRef,
        subscription_key: str,
    ) -> None:
        with self._connect() as con:
            con.execute(
                """
                DELETE FROM push_unsubscriptions
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND subscription_key = ?
                """,
                (*_conversation_values(conversation), subscription_key),
            )

    def filter_subscribed_conversations(
        self,
        conversations: Iterable[ConversationRef],
        subscription_key: str,
    ) -> list[ConversationRef]:
        requested = list(dict.fromkeys(conversations))
        if not requested:
            return []
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT conversation_platform, conversation_kind, conversation_id
                FROM push_unsubscriptions
                WHERE subscription_key = ?
                """,
                (subscription_key,),
            ).fetchall()
        blocked = {
            conversation
            for row in rows
            if (conversation := _conversation_from_row(row)) is not None
        }
        return [
            conversation
            for conversation in requested
            if conversation not in blocked
        ]

    def get_time_preference(
        self,
        conversation: ConversationRef,
        subscription_key: str,
        preference_type: PushPreferenceType,
    ) -> str | None:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT value FROM push_time_preferences
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND subscription_key = ?
                  AND preference_type = ?
                """,
                (
                    *_conversation_values(conversation),
                    subscription_key,
                    preference_type,
                ),
            ).fetchone()
        return None if row is None else str(row[0])

    def set_time_preference(
        self,
        conversation: ConversationRef,
        subscription_key: str,
        preference_type: PushPreferenceType,
        value: str,
    ) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO push_time_preferences (
                    conversation_platform, conversation_kind, conversation_id,
                    subscription_key, preference_type, value, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    *_conversation_values(conversation),
                    subscription_key,
                    preference_type,
                    value,
                    _now(),
                ),
            )

    def clear_time_preference(
        self,
        conversation: ConversationRef,
        subscription_key: str,
        preference_type: PushPreferenceType,
    ) -> None:
        with self._connect() as con:
            con.execute(
                """
                DELETE FROM push_time_preferences
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND subscription_key = ?
                  AND preference_type = ?
                """,
                (
                    *_conversation_values(conversation),
                    subscription_key,
                    preference_type,
                ),
            )

    def conversation_time_preferences(
        self,
        conversation: ConversationRef,
    ) -> dict[tuple[str, PushPreferenceType], str]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT subscription_key, preference_type, value
                FROM push_time_preferences
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ?
                """,
                _conversation_values(conversation),
            ).fetchall()
        return _time_preference_values(rows)

    def mark_daily_hint_sent(
        self,
        conversation: ConversationRef,
        hint_key: str,
        *,
        today: str | None = None,
    ) -> bool:
        delivered_on = today or datetime.now().astimezone().date().isoformat()
        values = _conversation_values(conversation)
        with self._connect() as con:
            row = con.execute(
                """
                SELECT delivered_on FROM push_daily_hints
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND hint_key = ?
                """,
                (*values, hint_key),
            ).fetchone()
            if row is not None and str(row[0]) == delivered_on:
                return False
            con.execute(
                """
                INSERT OR REPLACE INTO push_daily_hints (
                    conversation_platform, conversation_kind, conversation_id,
                    hint_key, delivered_on, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (*values, hint_key, delivered_on, _now()),
            )
        return True

    def all_time_preferences(
        self,
        *,
        platform: Platform | None = None,
        conversation_kind: ConversationKind | None = None,
        subscription_key: str | None = None,
        preference_type: PushPreferenceType | None = None,
    ) -> list[PushTimePreference]:
        clauses: list[str] = []
        params: list[str] = []
        if platform is not None:
            clauses.append("conversation_platform = ?")
            params.append(platform.value)
        if conversation_kind is not None:
            clauses.append("conversation_kind = ?")
            params.append(conversation_kind)
        if subscription_key is not None:
            clauses.append("subscription_key = ?")
            params.append(subscription_key)
        if preference_type is not None:
            clauses.append("preference_type = ?")
            params.append(preference_type)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT conversation_platform, conversation_kind, conversation_id,
                       subscription_key, preference_type, value, updated_at
                FROM push_time_preferences
                """
                + where,
                params,
            ).fetchall()
        preferences: list[PushTimePreference] = []
        for (
            platform_value,
            kind,
            target_id,
            key,
            stored_type,
            value,
            updated_at,
        ) in rows:
            conversation = _conversation_from_row((platform_value, kind, target_id))
            if conversation is None or stored_type not in {
                "cron_time",
                "activity_lead_hours",
            }:
                continue
            preferences.append(
                PushTimePreference(
                    conversation=conversation,
                    subscription_key=str(key),
                    preference_type=cast("PushPreferenceType", stored_type),
                    value=str(value),
                    updated_at=str(updated_at),
                )
            )
        return preferences

    def preference_conversations(self) -> set[ConversationRef]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT conversation_platform, conversation_kind, conversation_id
                FROM push_unsubscriptions
                UNION
                SELECT conversation_platform, conversation_kind, conversation_id
                FROM push_time_preferences
                """
            ).fetchall()
        return {
            conversation
            for row in rows
            if (conversation := _conversation_from_row(row)) is not None
        }

    def prune_invalid_preferences(
        self,
        *,
        valid_unsubscription_keys: Mapping[ConversationRef, AbstractSet[str]],
        valid_time_preferences: Mapping[
            ConversationRef,
            AbstractSet[PushTimePreferenceIdentity],
        ],
    ) -> PushPreferencePruneResult:
        with self._connect() as con:
            deleted_unsubscriptions = self._prune_unsubscriptions(
                con,
                valid_unsubscription_keys,
            )
            deleted_time_preferences = self._prune_time_preferences(
                con,
                valid_time_preferences,
            )
        return PushPreferencePruneResult(
            unsubscriptions_deleted=deleted_unsubscriptions,
            time_preferences_deleted=deleted_time_preferences,
        )

    def _prune_unsubscriptions(
        self,
        con: sqlite3.Connection,
        valid: Mapping[ConversationRef, AbstractSet[str]],
    ) -> int:
        rows = con.execute(
            """
            SELECT conversation_platform, conversation_kind, conversation_id,
                   subscription_key
            FROM push_unsubscriptions
            """
        ).fetchall()
        deleted = 0
        for platform_value, kind, target_id, key in rows:
            conversation = _conversation_from_row((platform_value, kind, target_id))
            if conversation is not None and str(key) in valid.get(conversation, set()):
                continue
            con.execute(
                """
                DELETE FROM push_unsubscriptions
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND subscription_key = ?
                """,
                (platform_value, kind, target_id, key),
            )
            deleted += 1
        return deleted

    def _prune_time_preferences(
        self,
        con: sqlite3.Connection,
        valid: Mapping[
            ConversationRef,
            AbstractSet[PushTimePreferenceIdentity],
        ],
    ) -> int:
        rows = con.execute(
            """
            SELECT conversation_platform, conversation_kind, conversation_id,
                   subscription_key, preference_type
            FROM push_time_preferences
            """
        ).fetchall()
        deleted = 0
        for platform_value, kind, target_id, key, preference_type in rows:
            conversation = _conversation_from_row((platform_value, kind, target_id))
            identity = (str(key), cast("PushPreferenceType", preference_type))
            if (
                conversation is not None
                and preference_type in {"cron_time", "activity_lead_hours"}
                and identity in valid.get(conversation, set())
            ):
                continue
            con.execute(
                """
                DELETE FROM push_time_preferences
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND subscription_key = ?
                  AND preference_type = ?
                """,
                (platform_value, kind, target_id, key, preference_type),
            )
            deleted += 1
        return deleted

    def _connect(self) -> AbstractContextManager[sqlite3.Connection]:
        return self._database.connect()


def _conversation_values(conversation: ConversationRef) -> tuple[str, str, str]:
    return ConversationIdentityColumns.from_conversation(conversation).values()


def _conversation_from_row(row: object) -> ConversationRef | None:
    platform_value, kind, target_id = tuple(row)  # type: ignore[arg-type]
    try:
        return ConversationRef(
            Platform(str(platform_value)),
            cast("ConversationKind", str(kind)),
            str(target_id),
        )
    except ValueError:
        return None


def _time_preference_values(
    rows: object,
) -> dict[tuple[str, PushPreferenceType], str]:
    preferences: dict[tuple[str, PushPreferenceType], str] = {}
    for key, preference_type, value in rows:  # type: ignore[union-attr]
        if preference_type not in {"cron_time", "activity_lead_hours"}:
            continue
        preferences[(str(key), cast("PushPreferenceType", preference_type))] = str(
            value
        )
    return preferences


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
