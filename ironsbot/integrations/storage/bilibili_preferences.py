from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.bilibili.preferences import BiliRuntimePushMode
    from ironsbot.services.messaging.subscriptions import PushTargetType

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS bili_push_preferences ("
    "target_type TEXT NOT NULL, target_id INTEGER NOT NULL, "
    "uid INTEGER NOT NULL, mode TEXT NOT NULL, updated_at TEXT NOT NULL, "
    "PRIMARY KEY (target_type, target_id, uid)"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_bili_push_preferences_uid "
    "ON bili_push_preferences (uid, target_type, target_id)",
)
_MIGRATIONS = (
    SqliteMigration(1, _SCHEMA),
)


class SqliteBiliPushPreferenceStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(path, migrations=_MIGRATIONS)

    def get_mode(
        self,
        target_type: PushTargetType,
        target_id: int,
        uid: int,
    ) -> BiliRuntimePushMode | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT mode FROM bili_push_preferences "
                "WHERE target_type = ? AND target_id = ? AND uid = ?",
                (target_type, target_id, uid),
            ).fetchone()
        mode = str(row[0]) if row is not None else ""
        if mode == "full":
            return "full"
        if mode == "link":
            return "link"
        return None

    def set_mode(
        self,
        target_type: PushTargetType,
        target_id: int,
        uid: int,
        mode: BiliRuntimePushMode,
    ) -> None:
        with self._database.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO bili_push_preferences "
                "(target_type, target_id, uid, mode, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    target_type,
                    target_id,
                    uid,
                    mode,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def clear_mode(
        self,
        target_type: PushTargetType,
        target_id: int,
        uid: int,
    ) -> None:
        with self._database.connect() as connection:
            connection.execute(
                "DELETE FROM bili_push_preferences "
                "WHERE target_type = ? AND target_id = ? AND uid = ?",
                (target_type, target_id, uid),
            )
