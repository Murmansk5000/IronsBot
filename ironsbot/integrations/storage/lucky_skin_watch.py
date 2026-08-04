# SPDX-License-Identifier: MIT
"""Actor-scoped lucky-skin watch preferences."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.platform_identity import ActorIdentityColumns
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.platform import ActorRef


_SCHEMA = """
CREATE TABLE IF NOT EXISTS lucky_skin_watch_preferences (
    actor_platform TEXT NOT NULL,
    actor_kind TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_scope_id TEXT NOT NULL DEFAULT '',
    skin_ids_json TEXT NOT NULL,
    initialized_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (actor_platform, actor_kind, actor_id, actor_scope_id)
)
"""
_MIGRATIONS = (SqliteMigration(1, (_SCHEMA,)),)
MIGRATION_NAMESPACE = "lucky_skin_watch"


class SqliteLuckySkinWatchPreferenceStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    def get(self, actor: ActorRef) -> tuple[int, ...] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT skin_ids_json FROM lucky_skin_watch_preferences
                WHERE actor_platform = ? AND actor_kind = ? AND actor_id = ?
                  AND actor_scope_id = ?
                """,
                ActorIdentityColumns.from_actor(actor).values(),
            ).fetchone()
        return None if row is None else _decode_skin_ids(row[0])

    def set(self, actor: ActorRef, skin_ids: tuple[int, ...]) -> None:
        normalized = _normalize_skin_ids(skin_ids)
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(normalized, separators=(",", ":"))
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO lucky_skin_watch_preferences (
                    actor_platform, actor_kind, actor_id, actor_scope_id,
                    skin_ids_json, initialized_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(actor_platform, actor_kind, actor_id, actor_scope_id)
                DO UPDATE SET
                    skin_ids_json = excluded.skin_ids_json,
                    updated_at = excluded.updated_at
                """,
                (*ActorIdentityColumns.from_actor(actor).values(), payload, now, now),
            )
def _decode_skin_ids(value: object) -> tuple[int, ...]:
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    if not isinstance(decoded, list):
        return ()
    try:
        return _normalize_skin_ids(tuple(int(item) for item in decoded))
    except (TypeError, ValueError):
        return ()


def _normalize_skin_ids(skin_ids: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(skin_id for skin_id in skin_ids if skin_id > 0))
