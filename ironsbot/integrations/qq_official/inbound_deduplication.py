# SPDX-License-Identifier: MIT
"""Persistent claims for QQ Official inbound message delivery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import time
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_DEFAULT_RETENTION_SECONDS = 24 * 60 * 60
_MIGRATIONS = (
    SqliteMigration(
        1,
        statements=(
            """
            CREATE TABLE qq_official_inbound_claims (
                app_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message_id TEXT NOT NULL,
                claimed_at REAL NOT NULL,
                PRIMARY KEY (app_id, event_type, message_id)
            )
            """,
            """
            CREATE INDEX qq_official_inbound_claims_claimed_at
            ON qq_official_inbound_claims (claimed_at)
            """,
        ),
    ),
)


@dataclass(slots=True)
class QQOfficialInboundDeduplicator:
    path: Path
    retention_seconds: float = _DEFAULT_RETENTION_SECONDS
    clock: Callable[[], float] = field(default=time, repr=False, compare=False)
    _database: SqliteDatabase = field(init=False, repr=False)
    _claim_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        if self.retention_seconds <= 0:
            raise ValueError(self.retention_seconds)
        self._database = SqliteDatabase(
            self.path,
            migrations=_MIGRATIONS,
            migration_namespace="qq_official_inbound_claims",
        )

    async def claim(
        self,
        *,
        app_id: str,
        event_type: str,
        message_id: str,
    ) -> bool:
        async with self._claim_lock:
            return await asyncio.to_thread(
                self._claim_sync,
                app_id,
                event_type,
                message_id,
            )

    def _claim_sync(self, app_id: str, event_type: str, message_id: str) -> bool:
        now = self.clock()
        with self._database.connect() as connection:
            connection.execute(
                "DELETE FROM qq_official_inbound_claims WHERE claimed_at < ?",
                (now - self.retention_seconds,),
            )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO qq_official_inbound_claims (
                    app_id, event_type, message_id, claimed_at
                ) VALUES (?, ?, ?, ?)
                """,
                (app_id, event_type, message_id, now),
            )
            return cursor.rowcount == 1
