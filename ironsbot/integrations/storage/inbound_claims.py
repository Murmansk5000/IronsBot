# SPDX-License-Identifier: MIT
"""Persistent, platform-scoped inbound delivery claims."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import time
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ironsbot.core.inbound_claims import InboundMessageKey

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
    SqliteMigration(
        2,
        statements=(
            "ALTER TABLE qq_official_inbound_claims "
            "RENAME TO qq_official_inbound_claims_v1",
            "DROP INDEX qq_official_inbound_claims_claimed_at",
            """
            CREATE TABLE qq_official_inbound_claims (
                app_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                claimed_at REAL NOT NULL,
                PRIMARY KEY (app_id, event_type, conversation_id, message_id)
            )
            """,
            """
            INSERT INTO qq_official_inbound_claims
            SELECT app_id, event_type, '', message_id, claimed_at
            FROM qq_official_inbound_claims_v1
            """,
            "DROP TABLE qq_official_inbound_claims_v1",
            "CREATE INDEX qq_official_inbound_claims_claimed_at "
            "ON qq_official_inbound_claims (claimed_at)",
        ),
    ),
    SqliteMigration(
        3,
        statements=(
            """
            CREATE TABLE inbound_message_claims (
                platform TEXT NOT NULL,
                account_id TEXT NOT NULL,
                conversation_kind TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                claimed_at REAL NOT NULL,
                PRIMARY KEY (
                    platform, account_id, conversation_kind,
                    conversation_id, message_id
                )
            )
            """,
            """
            INSERT INTO inbound_message_claims
            SELECT 'qq_official', app_id,
                CASE
                    WHEN event_type IN (
                        'GROUP_MESSAGE', 'GROUP_MESSAGE_CREATE',
                        'GROUP_AT_MESSAGE_CREATE', 'group'
                    ) THEN 'group'
                    WHEN event_type IN ('C2C_MESSAGE_CREATE', 'c2c') THEN 'private'
                    ELSE event_type
                END AS conversation_kind,
                conversation_id, message_id, MAX(claimed_at)
            FROM qq_official_inbound_claims
            GROUP BY app_id, conversation_kind, conversation_id, message_id
            """,
            "DROP TABLE qq_official_inbound_claims",
            "CREATE INDEX inbound_message_claims_claimed_at "
            "ON inbound_message_claims (claimed_at)",
        ),
    ),
)


@dataclass(slots=True)
class SqliteInboundMessageClaims:
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

    async def claim(self, key: InboundMessageKey) -> bool:
        async with self._claim_lock:
            return await asyncio.to_thread(self._claim_sync, key)

    def _claim_sync(self, key: InboundMessageKey) -> bool:
        now = self.clock()
        with self._database.connect() as connection:
            connection.execute(
                "DELETE FROM inbound_message_claims WHERE claimed_at <= ?",
                (now - self.retention_seconds,),
            )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO inbound_message_claims (
                    platform, account_id, conversation_kind,
                    conversation_id, message_id, claimed_at
                ) SELECT ?, ?, ?, ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM inbound_message_claims
                    WHERE platform = ? AND account_id = ?
                    AND conversation_kind = ? AND message_id = ?
                    AND conversation_id = ''
                )
                """,
                (
                    key.platform.value,
                    key.account_id,
                    key.conversation_kind,
                    key.conversation_id,
                    key.message_id,
                    now,
                    key.platform.value,
                    key.account_id,
                    key.conversation_kind,
                    key.message_id,
                ),
            )
            return cursor.rowcount == 1
