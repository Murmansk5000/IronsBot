# SPDX-License-Identifier: MIT
"""Persistent QQ Official recipient state derived from gateway events."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.core.platform import Platform
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from ironsbot.core.platform import ConversationRef

_SCHEMA = """
CREATE TABLE qq_official_recipient_states (
    official_app_id TEXT NOT NULL,
    conversation_kind TEXT NOT NULL
        CHECK (conversation_kind IN ('group', 'private')),
    recipient_openid TEXT NOT NULL,
    proactive_allowed INTEGER
        CHECK (proactive_allowed IS NULL OR proactive_allowed IN (0, 1)),
    updated_at REAL NOT NULL,
    PRIMARY KEY (official_app_id, conversation_kind, recipient_openid)
)
"""
_MIGRATIONS = (SqliteMigration(1, (_SCHEMA,)),)

_EVENT_RULES: dict[str, tuple[str, str, bool | None]] = {
    "C2C_MSG_RECEIVE": ("private", "openid", True),
    "C2C_MSG_REJECT": ("private", "openid", False),
    "FRIEND_ADD": ("private", "openid", None),
    "FRIEND_DEL": ("private", "openid", False),
    "GROUP_ADD_ROBOT": ("group", "group_openid", None),
    "GROUP_DEL_ROBOT": ("group", "group_openid", False),
    "GROUP_MSG_RECEIVE": ("group", "group_openid", True),
    "GROUP_MSG_REJECT": ("group", "group_openid", False),
}


@dataclass(slots=True)
class QQOfficialRecipientStateStore:
    """Persist explicit platform permission changes for proactive delivery."""

    path: Path
    clock: Callable[[], float] = time.time
    _database: SqliteDatabase = field(init=False, repr=False)
    _write_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        self._database = SqliteDatabase(
            self.path,
            migrations=_MIGRATIONS,
            migration_namespace="qq_official_recipient_states",
        )

    async def record_event(
        self,
        *,
        app_id: str,
        event_type: str,
        raw: Mapping[str, object],
    ) -> bool:
        rule = _EVENT_RULES.get(event_type)
        if rule is None:
            return False
        kind, field_name, allowed = rule
        recipient = str(raw.get(field_name, "")).strip()
        if not app_id.strip() or not recipient:
            return False
        async with self._write_lock:
            await asyncio.to_thread(
                self._record_sync,
                app_id.strip(),
                kind,
                recipient,
                allowed=allowed,
                updated_at=float(self.clock()),
            )
        return True

    async def allows_proactive(self, conversation: ConversationRef) -> bool:
        if (
            conversation.platform is not Platform.QQ_OFFICIAL
            or conversation.kind not in {"group", "private"}
            or conversation.account_id is None
        ):
            return False
        allowed = await asyncio.to_thread(
            self._read_sync,
            conversation.account_id,
            conversation.kind,
            conversation.id,
        )
        return allowed is not False

    def _record_sync(
        self,
        app_id: str,
        kind: str,
        recipient: str,
        *,
        allowed: bool | None,
        updated_at: float,
    ) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO qq_official_recipient_states (
                    official_app_id, conversation_kind, recipient_openid,
                    proactive_allowed, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (
                    official_app_id, conversation_kind, recipient_openid
                ) DO UPDATE SET
                    proactive_allowed = excluded.proactive_allowed,
                    updated_at = excluded.updated_at
                """,
                (
                    app_id,
                    kind,
                    recipient,
                    None if allowed is None else int(allowed),
                    updated_at,
                ),
            )

    def _read_sync(self, app_id: str, kind: str, recipient: str) -> bool | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT proactive_allowed
                FROM qq_official_recipient_states
                WHERE official_app_id = ?
                  AND conversation_kind = ?
                  AND recipient_openid = ?
                """,
                (app_id, kind, recipient),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return bool(row[0])
