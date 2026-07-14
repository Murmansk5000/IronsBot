# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ironsbot.shared.messaging.push_subscription_models import (
    PushPreferenceType,
    PushTargetType,
    PushTimePreference,
)
from ironsbot.shared.sqlite import open_sqlite_schema

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable
    from contextlib import AbstractContextManager

PUSH_SUBSCRIPTION_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS push_unsubscriptions ("
    "target_type TEXT NOT NULL, "
    "target_id INTEGER NOT NULL, "
    "subscription_key TEXT NOT NULL, "
    "feature TEXT NOT NULL, "
    "created_at TEXT NOT NULL, "
    "PRIMARY KEY (target_type, target_id, subscription_key)"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_push_unsubscriptions_lookup "
    "ON push_unsubscriptions (target_type, subscription_key, target_id)",
    "CREATE TABLE IF NOT EXISTS push_time_preferences ("
    "target_type TEXT NOT NULL, "
    "target_id INTEGER NOT NULL, "
    "subscription_key TEXT NOT NULL, "
    "preference_type TEXT NOT NULL, "
    "value TEXT NOT NULL, "
    "updated_at TEXT NOT NULL, "
    "PRIMARY KEY (target_type, target_id, subscription_key, preference_type)"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_push_time_preferences_lookup "
    "ON push_time_preferences "
    "(target_type, subscription_key, preference_type, target_id)",
    "CREATE TABLE IF NOT EXISTS push_daily_hints ("
    "target_type TEXT NOT NULL, "
    "target_id INTEGER NOT NULL, "
    "hint_key TEXT NOT NULL, "
    "delivered_on TEXT NOT NULL, "
    "updated_at TEXT NOT NULL, "
    "PRIMARY KEY (target_type, target_id, hint_key)"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_push_daily_hints_lookup "
    "ON push_daily_hints (target_type, hint_key, delivered_on)",
)


class PushUnsubscribeStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def target_unsubscribed_keys(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> set[str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT subscription_key FROM push_unsubscriptions "
                "WHERE target_type = ? AND target_id = ?",
                (target_type, int(target_id)),
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
                "SELECT 1 FROM push_unsubscriptions "
                "WHERE target_type = ? AND target_id = ? AND subscription_key = ?",
                (target_type, int(target_id), subscription_key),
            ).fetchone()
        return row is not None

    def unsubscribe_target(
        self,
        target_type: PushTargetType,
        target_id: int,
        subscription_key: str,
        feature: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO push_unsubscriptions "
                "(target_type, target_id, subscription_key, feature, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (target_type, int(target_id), subscription_key, feature, now),
            )

    def restore_target(
        self,
        target_type: PushTargetType,
        target_id: int,
        subscription_key: str,
    ) -> None:
        with self._connect() as con:
            con.execute(
                "DELETE FROM push_unsubscriptions "
                "WHERE target_type = ? AND target_id = ? AND subscription_key = ?",
                (target_type, int(target_id), subscription_key),
            )

    def filter_subscribed_target_ids(
        self,
        target_type: PushTargetType,
        target_ids: Iterable[int],
        subscription_key: str,
    ) -> list[int]:
        deduped_target_ids = list(
            dict.fromkeys(int(target_id) for target_id in target_ids)
        )
        if not deduped_target_ids:
            return []
        with self._connect() as con:
            rows = con.execute(
                "SELECT target_id FROM push_unsubscriptions "
                "WHERE target_type = ? AND subscription_key = ?",
                (target_type, subscription_key),
            ).fetchall()
        requested = set(deduped_target_ids)
        blocked = {int(row[0]) for row in rows if int(row[0]) in requested}
        return [
            target_id for target_id in deduped_target_ids if target_id not in blocked
        ]

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
                "SELECT value FROM push_time_preferences "
                "WHERE target_type = ? AND target_id = ? "
                "AND subscription_key = ? AND preference_type = ?",
                (target_type, int(target_id), subscription_key, preference_type),
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
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO push_time_preferences "
                "(target_type, target_id, subscription_key, preference_type, "
                "value, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    target_type,
                    int(target_id),
                    subscription_key,
                    preference_type,
                    value,
                    now,
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
                "DELETE FROM push_time_preferences "
                "WHERE target_type = ? AND target_id = ? "
                "AND subscription_key = ? AND preference_type = ?",
                (target_type, int(target_id), subscription_key, preference_type),
            )

    def target_time_preferences(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> dict[tuple[str, PushPreferenceType], str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT subscription_key, preference_type, value "
                "FROM push_time_preferences "
                "WHERE target_type = ? AND target_id = ?",
                (target_type, int(target_id)),
            ).fetchall()
        preferences: dict[tuple[str, PushPreferenceType], str] = {}
        for key, preference_type, value in rows:
            preference_type_text = str(preference_type)
            if preference_type_text not in {"cron_time", "activity_lead_hours"}:
                continue
            preferences[
                (str(key), cast("PushPreferenceType", preference_type_text))
            ] = str(value)
        return preferences

    def mark_daily_hint_sent(
        self,
        target_type: PushTargetType,
        target_id: int,
        hint_key: str,
        *,
        today: str | None = None,
    ) -> bool:
        delivered_on = today or datetime.now().astimezone().date().isoformat()
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            row = con.execute(
                "SELECT delivered_on FROM push_daily_hints "
                "WHERE target_type = ? AND target_id = ? AND hint_key = ?",
                (target_type, int(target_id), hint_key),
            ).fetchone()
            if row is not None and str(row[0]) == delivered_on:
                return False
            con.execute(
                "INSERT OR REPLACE INTO push_daily_hints "
                "(target_type, target_id, hint_key, delivered_on, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (target_type, int(target_id), hint_key, delivered_on, now),
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
                "SELECT target_type, target_id, subscription_key, preference_type, "
                "value, updated_at FROM push_time_preferences "
                "WHERE (? IS NULL OR target_type = ?) "
                "AND (? IS NULL OR subscription_key = ?) "
                "AND (? IS NULL OR preference_type = ?)",
                (
                    target_type,
                    target_type,
                    subscription_key,
                    subscription_key,
                    preference_type,
                    preference_type,
                ),
            ).fetchall()
        return [
            PushTimePreference(
                target_type=target_type_row,
                target_id=int(target_id),
                subscription_key=str(key),
                preference_type=preference_type_row,
                value=str(value),
                updated_at=str(updated_at),
            )
            for (
                target_type_row,
                target_id,
                key,
                preference_type_row,
                value,
                updated_at,
            ) in rows
            if target_type_row in {"private", "group"}
            and preference_type_row in {"cron_time", "activity_lead_hours"}
        ]

    def _connect(self) -> AbstractContextManager[sqlite3.Connection]:
        return open_sqlite_schema(self.path, PUSH_SUBSCRIPTION_SCHEMA)
