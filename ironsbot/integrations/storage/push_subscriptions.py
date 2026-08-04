# SPDX-License-Identifier: MIT
"""Conversation-scoped scheduled-push preferences.

The public methods retain the current OneBot-oriented ``target_type`` and
``target_id`` parameters while the repository persists only platform-neutral
``ConversationRef`` columns. The adapter boundary will replace those legacy
parameters before another delivery platform is enabled.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.storage.platform_identity import (
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration
from ironsbot.services.messaging.subscriptions import (
    PushPreferencePruneResult,
    PushPreferenceTarget,
    PushPreferenceType,
    PushTargetType,
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
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._database = SqliteDatabase(
            self.path,
            migrations=PUSH_SUBSCRIPTION_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    def target_unsubscribed_keys(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> set[str]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT subscription_key FROM push_unsubscriptions
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ?
                """,
                _conversation_values(target_type, target_id),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def is_target_unsubscribed(
        self,
        target_type: PushTargetType,
        target_id: int,
        subscription_key: str,
    ) -> bool:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT 1 FROM push_unsubscriptions
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND subscription_key = ?
                """,
                (*_conversation_values(target_type, target_id), subscription_key),
            ).fetchone()
        return row is not None

    def unsubscribe_target(
        self,
        target_type: PushTargetType,
        target_id: int,
        subscription_key: str,
        feature: str,
    ) -> None:
        now = _now()
        with self._connect() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO push_unsubscriptions (
                    conversation_platform, conversation_kind, conversation_id,
                    subscription_key, feature, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    *_conversation_values(target_type, target_id),
                    subscription_key,
                    feature,
                    now,
                ),
            )

    def restore_target(
        self,
        target_type: PushTargetType,
        target_id: int,
        subscription_key: str,
    ) -> None:
        with self._connect() as con:
            con.execute(
                """
                DELETE FROM push_unsubscriptions
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND subscription_key = ?
                """,
                (*_conversation_values(target_type, target_id), subscription_key),
            )

    def filter_subscribed_target_ids(
        self,
        target_type: PushTargetType,
        target_ids: Iterable[int],
        subscription_key: str,
    ) -> list[int]:
        requested = list(dict.fromkeys(int(target_id) for target_id in target_ids))
        if not requested:
            return []
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT conversation_id FROM push_unsubscriptions
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND subscription_key = ?
                """,
                (Platform.ONEBOT.value, target_type, subscription_key),
            ).fetchall()
        wanted = set(requested)
        blocked = {
            int(row[0])
            for row in rows
            if str(row[0]).isdecimal() and int(row[0]) in wanted
        }
        return [target_id for target_id in requested if target_id not in blocked]

    def filter_subscribed_user_ids(
        self,
        user_ids: Iterable[int],
        subscription_key: str,
    ) -> list[int]:
        return self.filter_subscribed_target_ids("private", user_ids, subscription_key)

    def filter_subscribed_group_ids(
        self,
        group_ids: Iterable[int],
        subscription_key: str,
    ) -> list[int]:
        return self.filter_subscribed_target_ids("group", group_ids, subscription_key)

    def get_time_preference(
        self,
        target_type: PushTargetType,
        target_id: int,
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
                    *_conversation_values(target_type, target_id),
                    subscription_key,
                    preference_type,
                ),
            ).fetchone()
        return None if row is None else str(row[0])

    def set_time_preference(
        self,
        target_type: PushTargetType,
        target_id: int,
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
                    *_conversation_values(target_type, target_id),
                    subscription_key,
                    preference_type,
                    value,
                    _now(),
                ),
            )

    def clear_time_preference(
        self,
        target_type: PushTargetType,
        target_id: int,
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
                    *_conversation_values(target_type, target_id),
                    subscription_key,
                    preference_type,
                ),
            )

    def target_time_preferences(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> dict[tuple[str, PushPreferenceType], str]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT subscription_key, preference_type, value
                FROM push_time_preferences
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ?
                """,
                _conversation_values(target_type, target_id),
            ).fetchall()
        return _time_preference_values(rows)

    def mark_daily_hint_sent(
        self,
        target_type: PushTargetType,
        target_id: int,
        hint_key: str,
        *,
        today: str | None = None,
    ) -> bool:
        delivered_on = today or datetime.now().astimezone().date().isoformat()
        values = _conversation_values(target_type, target_id)
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
        target_type: PushTargetType | None = None,
        subscription_key: str | None = None,
        preference_type: PushPreferenceType | None = None,
    ) -> list[PushTimePreference]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT conversation_platform, conversation_kind, conversation_id,
                       subscription_key, preference_type, value, updated_at
                FROM push_time_preferences
                WHERE conversation_platform = ?
                  AND (? IS NULL OR conversation_kind = ?)
                  AND (? IS NULL OR subscription_key = ?)
                  AND (? IS NULL OR preference_type = ?)
                """,
                (
                    Platform.ONEBOT.value,
                    target_type,
                    target_type,
                    subscription_key,
                    subscription_key,
                    preference_type,
                    preference_type,
                ),
            ).fetchall()
        result: list[PushTimePreference] = []
        for _platform, kind, target_id, key, stored_type, value, updated_at in rows:
            if kind not in {"private", "group"} or not str(target_id).isdecimal():
                continue
            if stored_type not in {"cron_time", "activity_lead_hours"}:
                continue
            result.append(
                PushTimePreference(
                    target_type=cast("PushTargetType", kind),
                    target_id=int(target_id),
                    subscription_key=str(key),
                    preference_type=cast("PushPreferenceType", stored_type),
                    value=str(value),
                    updated_at=str(updated_at),
                )
            )
        return result

    def preference_targets(self) -> set[PushPreferenceTarget]:
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
            target
            for row in rows
            if (target := _legacy_onebot_target(row)) is not None
        }

    def prune_invalid_preferences(
        self,
        *,
        valid_unsubscription_keys: Mapping[
            PushPreferenceTarget,
            AbstractSet[str],
        ],
        valid_time_preferences: Mapping[
            PushPreferenceTarget,
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
        valid: Mapping[PushPreferenceTarget, AbstractSet[str]],
    ) -> int:
        rows = con.execute(
            """
            SELECT conversation_platform, conversation_kind, conversation_id,
                   subscription_key
            FROM push_unsubscriptions
            """
        ).fetchall()
        deleted = 0
        for platform, kind, target_id, key in rows:
            target = _legacy_onebot_target((platform, kind, target_id))
            if target is None or str(key) in valid.get(target, set()):
                continue
            con.execute(
                """
                DELETE FROM push_unsubscriptions
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND subscription_key = ?
                """,
                (platform, kind, target_id, key),
            )
            deleted += 1
        return deleted

    def _prune_time_preferences(
        self,
        con: sqlite3.Connection,
        valid: Mapping[PushPreferenceTarget, AbstractSet[PushTimePreferenceIdentity]],
    ) -> int:
        rows = con.execute(
            """
            SELECT conversation_platform, conversation_kind, conversation_id,
                   subscription_key, preference_type
            FROM push_time_preferences
            """
        ).fetchall()
        deleted = 0
        for platform, kind, target_id, key, preference_type in rows:
            target = _legacy_onebot_target((platform, kind, target_id))
            identity = (str(key), cast("PushPreferenceType", preference_type))
            if (
                target is None
                or preference_type not in {"cron_time", "activity_lead_hours"}
                or identity in valid.get(target, set())
            ):
                continue
            con.execute(
                """
                DELETE FROM push_time_preferences
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND subscription_key = ?
                  AND preference_type = ?
                """,
                (platform, kind, target_id, key, preference_type),
            )
            deleted += 1
        return deleted

    def _connect(self) -> AbstractContextManager[sqlite3.Connection]:
        return self._database.connect()


def _conversation_values(
    target_type: PushTargetType,
    target_id: int,
) -> tuple[str, str, str]:
    conversation = ConversationRef(
        Platform.ONEBOT,
        target_type,
        str(int(target_id)),
    )
    return ConversationIdentityColumns.from_conversation(conversation).values()


def _legacy_onebot_target(row: object) -> PushPreferenceTarget | None:
    platform, kind, target_id = tuple(row)  # type: ignore[arg-type]
    if (
        platform != Platform.ONEBOT.value
        or kind not in {"private", "group"}
        or not str(target_id).isdecimal()
    ):
        return None
    return cast("PushTargetType", kind), int(target_id)


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
