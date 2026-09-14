# SPDX-License-Identifier: MIT
"""SQLite persistence for explicit OneBot-to-QQ-Official identity links."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration
from ironsbot.services.identity_link_store import (
    CrossPlatformIdentityLink,
    IdentityLinkChallengeExpiredError,
    IdentityLinkChallengeInvalidError,
    IdentityLinkConflictError,
    OfficialIdentity,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from ironsbot.core.platform import ActorKind

_MIGRATIONS = (
    SqliteMigration(
        1,
        statements=(
            """
            CREATE TABLE identity_link_challenges (
                token_hash TEXT PRIMARY KEY,
                onebot_qq_id TEXT NOT NULL,
                official_app_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                consumed_at REAL
            )
            """,
            """
            CREATE INDEX identity_link_challenges_owner
            ON identity_link_challenges (
                onebot_qq_id, official_app_id, consumed_at
            )
            """,
            """
            CREATE TABLE cross_platform_identity_links (
                official_app_id TEXT NOT NULL,
                official_kind TEXT NOT NULL
                    CHECK (official_kind IN ('member', 'user')),
                official_openid TEXT NOT NULL,
                official_scope_id TEXT NOT NULL DEFAULT '',
                onebot_qq_id TEXT NOT NULL,
                linked_at REAL NOT NULL,
                PRIMARY KEY (
                    official_app_id, official_kind,
                    official_openid, official_scope_id
                )
            )
            """,
            """
            CREATE INDEX cross_platform_identity_links_onebot
            ON cross_platform_identity_links (onebot_qq_id, official_app_id)
            """,
            """
            CREATE TABLE identity_link_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                onebot_qq_id TEXT NOT NULL,
                official_app_id TEXT NOT NULL,
                official_kind TEXT NOT NULL DEFAULT '',
                official_openid TEXT NOT NULL DEFAULT '',
                official_scope_id TEXT NOT NULL DEFAULT '',
                occurred_at REAL NOT NULL
            )
            """,
        ),
    ),
)


@dataclass(slots=True)
class SqliteIdentityLinkStore:
    path: Path
    _database: SqliteDatabase = field(init=False, repr=False)
    _write_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        self._database = SqliteDatabase(
            self.path,
            migrations=_MIGRATIONS,
            migration_namespace="cross_platform_identity_links",
        )

    async def issue(
        self,
        *,
        token_hash: str,
        onebot_qq_id: str,
        official_app_id: str,
        created_at: float,
        expires_at: float,
    ) -> None:
        async with self._write_lock:
            await asyncio.to_thread(
                self._issue_sync,
                token_hash,
                onebot_qq_id,
                official_app_id,
                created_at,
                expires_at,
            )

    def _issue_sync(
        self,
        token_hash: str,
        onebot_qq_id: str,
        official_app_id: str,
        created_at: float,
        expires_at: float,
    ) -> None:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE identity_link_challenges
                SET consumed_at = ?
                WHERE onebot_qq_id = ? AND official_app_id = ?
                  AND consumed_at IS NULL
                """,
                (created_at, onebot_qq_id, official_app_id),
            )
            connection.execute(
                """
                INSERT INTO identity_link_challenges (
                    token_hash, onebot_qq_id, official_app_id,
                    created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    token_hash,
                    onebot_qq_id,
                    official_app_id,
                    created_at,
                    expires_at,
                ),
            )
            _audit(
                connection,
                action="issued",
                onebot_qq_id=onebot_qq_id,
                official_app_id=official_app_id,
                occurred_at=created_at,
            )

    async def consume(
        self,
        *,
        token_hash: str,
        official: OfficialIdentity,
        now: float,
    ) -> CrossPlatformIdentityLink:
        async with self._write_lock:
            return await asyncio.to_thread(
                self._consume_sync,
                token_hash,
                official,
                now,
            )

    def _consume_sync(
        self,
        token_hash: str,
        official: OfficialIdentity,
        now: float,
    ) -> CrossPlatformIdentityLink:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            challenge = connection.execute(
                """
                SELECT onebot_qq_id, official_app_id, expires_at, consumed_at
                FROM identity_link_challenges WHERE token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if challenge is None or challenge[3] is not None:
                raise IdentityLinkChallengeInvalidError
            if str(challenge[1]) != official.app_id:
                raise IdentityLinkChallengeInvalidError
            if float(challenge[2]) < now:
                raise IdentityLinkChallengeExpiredError

            onebot_qq_id = str(challenge[0])
            existing = connection.execute(
                """
                SELECT onebot_qq_id FROM cross_platform_identity_links
                WHERE official_app_id = ? AND official_kind = ?
                  AND official_openid = ? AND official_scope_id = ?
                """,
                (
                    official.app_id,
                    official.kind,
                    official.openid,
                    official.scope_id,
                ),
            ).fetchone()
            if existing is not None and str(existing[0]) != onebot_qq_id:
                raise IdentityLinkConflictError(str(existing[0]))
            connection.execute(
                """
                INSERT INTO cross_platform_identity_links (
                    official_app_id, official_kind, official_openid,
                    official_scope_id, onebot_qq_id, linked_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    official_app_id, official_kind,
                    official_openid, official_scope_id
                ) DO UPDATE SET linked_at = excluded.linked_at
                """,
                (
                    official.app_id,
                    official.kind,
                    official.openid,
                    official.scope_id,
                    onebot_qq_id,
                    now,
                ),
            )
            connection.execute(
                "UPDATE identity_link_challenges SET consumed_at = ? "
                "WHERE token_hash = ?",
                (now, token_hash),
            )
            _audit(
                connection,
                action="linked",
                onebot_qq_id=onebot_qq_id,
                official=official,
                occurred_at=now,
            )
            return CrossPlatformIdentityLink(onebot_qq_id, official, now)

    async def for_onebot(
        self,
        onebot_qq_id: str,
    ) -> tuple[CrossPlatformIdentityLink, ...]:
        return await asyncio.to_thread(self._for_onebot_sync, onebot_qq_id)

    def _for_onebot_sync(
        self,
        onebot_qq_id: str,
    ) -> tuple[CrossPlatformIdentityLink, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT official_app_id, official_kind, official_openid,
                       official_scope_id, linked_at
                FROM cross_platform_identity_links
                WHERE onebot_qq_id = ? ORDER BY official_app_id, linked_at
                """,
                (onebot_qq_id,),
            ).fetchall()
        return tuple(
            CrossPlatformIdentityLink(
                onebot_qq_id,
                OfficialIdentity(
                    str(row[0]),
                    cast("ActorKind", str(row[1])),
                    str(row[2]),
                    str(row[3]),
                ),
                float(row[4]),
            )
            for row in rows
        )

    async def for_official(
        self,
        official: OfficialIdentity,
    ) -> CrossPlatformIdentityLink | None:
        return await asyncio.to_thread(self._for_official_sync, official)

    def _for_official_sync(
        self,
        official: OfficialIdentity,
    ) -> CrossPlatformIdentityLink | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT onebot_qq_id, linked_at
                FROM cross_platform_identity_links
                WHERE official_app_id = ? AND official_kind = ?
                  AND official_openid = ? AND official_scope_id = ?
                """,
                (
                    official.app_id,
                    official.kind,
                    official.openid,
                    official.scope_id,
                ),
            ).fetchone()
        if row is None:
            return None
        return CrossPlatformIdentityLink(str(row[0]), official, float(row[1]))

    async def revoke_onebot(self, onebot_qq_id: str, *, now: float) -> int:
        async with self._write_lock:
            return await asyncio.to_thread(self._revoke_onebot_sync, onebot_qq_id, now)

    def _revoke_onebot_sync(self, onebot_qq_id: str, now: float) -> int:
        links = self._for_onebot_sync(onebot_qq_id)
        if not links:
            return 0
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM cross_platform_identity_links WHERE onebot_qq_id = ?",
                (onebot_qq_id,),
            )
            for link in links:
                _audit(
                    connection,
                    action="revoked",
                    onebot_qq_id=onebot_qq_id,
                    official=link.official,
                    occurred_at=now,
                )
        return len(links)

    async def revoke_official(self, official: OfficialIdentity, *, now: float) -> bool:
        async with self._write_lock:
            return await asyncio.to_thread(self._revoke_official_sync, official, now)

    def _revoke_official_sync(self, official: OfficialIdentity, now: float) -> bool:
        link = self._for_official_sync(official)
        if link is None:
            return False
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                DELETE FROM cross_platform_identity_links
                WHERE official_app_id = ? AND official_kind = ?
                  AND official_openid = ? AND official_scope_id = ?
                """,
                (
                    official.app_id,
                    official.kind,
                    official.openid,
                    official.scope_id,
                ),
            )
            _audit(
                connection,
                action="revoked",
                onebot_qq_id=link.onebot_qq_id,
                official=official,
                occurred_at=now,
            )
        return True


def _audit(  # noqa: PLR0913 - normalized audit row fields are intentionally explicit
    connection: sqlite3.Connection,
    *,
    action: str,
    onebot_qq_id: str,
    official_app_id: str = "",
    official: OfficialIdentity | None = None,
    occurred_at: float,
) -> None:
    connection.execute(
        """
        INSERT INTO identity_link_audit (
            action, onebot_qq_id, official_app_id, official_kind,
            official_openid, official_scope_id, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            action,
            onebot_qq_id,
            official.app_id if official is not None else official_app_id,
            official.kind if official is not None else "",
            official.openid if official is not None else "",
            official.scope_id if official is not None else "",
            occurred_at,
        ),
    )
