# SPDX-License-Identifier: MIT
"""Conversation-scoped Bilibili push preferences."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.storage.platform_identity import (
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.bilibili.preferences import BiliRuntimePushMode
    from ironsbot.services.messaging.subscriptions import PushTargetType


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS bili_push_preferences (
        conversation_platform TEXT NOT NULL,
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        uid INTEGER NOT NULL,
        mode TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (conversation_platform, conversation_kind, conversation_id, uid)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_bili_push_preferences_uid
    ON bili_push_preferences (
        uid, conversation_platform, conversation_kind, conversation_id
    )
    """,
)
_MIGRATIONS = (SqliteMigration(1, _SCHEMA),)
MIGRATION_NAMESPACE = "bilibili_preferences"


class SqliteBiliPushPreferenceStore:
    """Persist modes by a neutral conversation identity."""

    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    def get_mode(
        self,
        target_type: PushTargetType,
        target_id: int,
        uid: int,
    ) -> BiliRuntimePushMode | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT mode FROM bili_push_preferences
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND uid = ?
                """,
                (*_conversation_values(target_type, target_id), uid),
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
                """
                INSERT OR REPLACE INTO bili_push_preferences (
                    conversation_platform, conversation_kind, conversation_id,
                    uid, mode, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    *_conversation_values(target_type, target_id),
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
                """
                DELETE FROM bili_push_preferences
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND uid = ?
                """,
                (*_conversation_values(target_type, target_id), uid),
            )


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
