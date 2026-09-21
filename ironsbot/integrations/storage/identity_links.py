# SPDX-License-Identifier: MIT
"""SQLite persistence for explicit OneBot-to-QQ-Official identity links."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from ironsbot.integrations.storage.identity_link_schema import (
    IDENTITY_LINK_MIGRATIONS,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase
from ironsbot.services.identity_link_store import (
    CrossPlatformGroupLink,
    CrossPlatformIdentityLink,
    GroupLinkConflictError,
    IdentityLinkChallengeExpiredError,
    IdentityLinkChallengeInvalidError,
    IdentityLinkConflictError,
    OfficialIdentity,
    OfficialUnionObservation,
    UnionIdentityConflictError,
    UnionIdentityEvidenceChangedError,
    canonical_official_identity,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from ironsbot.core.platform import ActorKind, OfficialUnionIdentity


@dataclass(slots=True)
class SqliteIdentityLinkStore:
    path: Path
    _database: SqliteDatabase = field(init=False, repr=False)
    _write_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        self._database = SqliteDatabase(
            self.path,
            migrations=IDENTITY_LINK_MIGRATIONS,
            migration_namespace="cross_platform_identity_links",
        )

    async def observe_union_identity(
        self,
        *,
        official: OfficialIdentity,
        union_identity: OfficialUnionIdentity,
        now: float,
    ) -> tuple[CrossPlatformIdentityLink, ...]:
        async with self._write_lock:
            return await asyncio.to_thread(
                self._observe_union_identity_sync,
                official,
                union_identity,
                now,
            )

    def _observe_union_identity_sync(
        self,
        official: OfficialIdentity,
        union_identity: OfficialUnionIdentity,
        now: float,
    ) -> tuple[CrossPlatformIdentityLink, ...]:
        official = canonical_official_identity(official)
        union_openid = union_identity.union_openid or ""
        union_user_account = union_identity.union_user_account or ""
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """
                SELECT union_openid, union_user_account
                FROM official_union_identities
                WHERE official_app_id = ? AND official_kind = ?
                  AND official_openid = ? AND official_scope_id = ?
                """,
                _official_values(official),
            ).fetchone()
            if current is not None and (
                (union_openid and str(current[0]) and str(current[0]) != union_openid)
                or (
                    union_user_account
                    and str(current[1])
                    and str(current[1]) != union_user_account
                )
            ):
                raise UnionIdentityEvidenceChangedError

            rows = connection.execute(
                """
                SELECT official_app_id, official_kind,
                       official_openid, official_scope_id
                FROM official_union_identities
                WHERE (? <> '' AND union_openid = ?)
                   OR (? <> '' AND union_user_account = ?)
                """,
                (
                    union_openid,
                    union_openid,
                    union_user_account,
                    union_user_account,
                ),
            ).fetchall()
            endpoints = {
                _official_values(official),
                *(tuple(str(value) for value in row) for row in rows),
            }
            owners = {
                str(row[0])
                for endpoint in endpoints
                if (
                    row := connection.execute(
                        """
                        SELECT onebot_qq_id
                        FROM cross_platform_identity_links
                        WHERE official_app_id = ? AND official_kind = ?
                          AND official_openid = ? AND official_scope_id = ?
                        """,
                        endpoint,
                    ).fetchone()
                )
                is not None
            }
            if len(owners) > 1:
                raise UnionIdentityConflictError(len(owners))

            connection.execute(
                """
                INSERT INTO official_union_identities (
                    official_app_id, official_kind, official_openid,
                    official_scope_id, union_openid,
                    union_user_account, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    official_app_id, official_kind,
                    official_openid, official_scope_id
                ) DO UPDATE SET
                    union_openid = CASE
                        WHEN excluded.union_openid <> ''
                        THEN excluded.union_openid
                        ELSE official_union_identities.union_openid
                    END,
                    union_user_account = CASE
                        WHEN excluded.union_user_account <> ''
                        THEN excluded.union_user_account
                        ELSE official_union_identities.union_user_account
                    END,
                    observed_at = excluded.observed_at
                """,
                (*_official_values(official), union_openid, union_user_account, now),
            )
            if not owners:
                return ()

            onebot_qq_id = next(iter(owners))
            links: list[CrossPlatformIdentityLink] = []
            for endpoint in endpoints:
                endpoint_identity = OfficialIdentity(
                    endpoint[0],
                    cast("ActorKind", endpoint[1]),
                    endpoint[2],
                    endpoint[3],
                )
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
                    (*endpoint, onebot_qq_id, now),
                )
                links.append(
                    CrossPlatformIdentityLink(onebot_qq_id, endpoint_identity, now)
                )
            return tuple(links)

    async def all_union_identities(self) -> tuple[OfficialUnionObservation, ...]:
        return await asyncio.to_thread(self._all_union_identities_sync)

    def _all_union_identities_sync(self) -> tuple[OfficialUnionObservation, ...]:
        from ironsbot.core.platform import OfficialUnionIdentity

        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT official_app_id, official_kind, official_openid,
                       official_scope_id, union_openid,
                       union_user_account, observed_at
                FROM official_union_identities
                ORDER BY observed_at, official_app_id, official_openid
                """
            ).fetchall()
        return tuple(
            OfficialUnionObservation(
                OfficialIdentity(
                    str(row[0]),
                    cast("ActorKind", str(row[1])),
                    str(row[2]),
                    str(row[3]),
                ),
                OfficialUnionIdentity(
                    union_openid=str(row[4]) or None,
                    union_user_account=str(row[5]) or None,
                ),
                float(row[6]),
            )
            for row in rows
        )

    async def link_group_verified(
        self,
        *,
        onebot_group_id: str,
        official_app_id: str,
        official_group_openid: str,
        now: float,
    ) -> CrossPlatformGroupLink:
        async with self._write_lock:
            return await asyncio.to_thread(
                self._link_group_verified_sync,
                onebot_group_id,
                official_app_id,
                official_group_openid,
                now,
            )

    def _link_group_verified_sync(
        self,
        onebot_group_id: str,
        official_app_id: str,
        official_group_openid: str,
        now: float,
    ) -> CrossPlatformGroupLink:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT official_group_openid, onebot_group_id
                FROM cross_platform_group_links
                WHERE official_app_id = ?
                  AND (official_group_openid = ? OR onebot_group_id = ?)
                """,
                (official_app_id, official_group_openid, onebot_group_id),
            ).fetchall()
            if any(
                str(row[0]) != official_group_openid or str(row[1]) != onebot_group_id
                for row in rows
            ):
                raise GroupLinkConflictError
            connection.execute(
                """
                INSERT INTO cross_platform_group_links (
                    official_app_id, official_group_openid,
                    onebot_group_id, linked_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT (official_app_id, official_group_openid)
                DO UPDATE SET linked_at = excluded.linked_at
                """,
                (official_app_id, official_group_openid, onebot_group_id, now),
            )
        return CrossPlatformGroupLink(
            onebot_group_id,
            official_app_id,
            official_group_openid,
            now,
        )

    async def all_group_links(self) -> tuple[CrossPlatformGroupLink, ...]:
        return await asyncio.to_thread(self._all_group_links_sync)

    def _all_group_links_sync(self) -> tuple[CrossPlatformGroupLink, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT onebot_group_id, official_app_id,
                       official_group_openid, linked_at
                FROM cross_platform_group_links
                ORDER BY official_app_id, official_group_openid
                """
            ).fetchall()
        return tuple(
            CrossPlatformGroupLink(
                str(row[0]),
                str(row[1]),
                str(row[2]),
                float(row[3]),
            )
            for row in rows
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
        official = canonical_official_identity(official)
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

    async def link_verified(
        self,
        *,
        onebot_qq_id: str,
        official: OfficialIdentity,
        now: float,
    ) -> CrossPlatformIdentityLink:
        async with self._write_lock:
            return await asyncio.to_thread(
                self._link_verified_sync,
                onebot_qq_id,
                official,
                now,
            )

    def _link_verified_sync(
        self,
        onebot_qq_id: str,
        official: OfficialIdentity,
        now: float,
    ) -> CrossPlatformIdentityLink:
        official = canonical_official_identity(official)
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
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
            _audit(
                connection,
                action="observed_link",
                onebot_qq_id=onebot_qq_id,
                official=official,
                occurred_at=now,
            )
        return CrossPlatformIdentityLink(onebot_qq_id, official, now)

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

    async def all_links(self) -> tuple[CrossPlatformIdentityLink, ...]:
        return await asyncio.to_thread(self._all_links_sync)

    def _all_links_sync(self) -> tuple[CrossPlatformIdentityLink, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT onebot_qq_id, official_app_id, official_kind,
                       official_openid, official_scope_id, linked_at
                FROM cross_platform_identity_links
                ORDER BY official_app_id, official_openid
                """
            ).fetchall()
        return tuple(
            CrossPlatformIdentityLink(
                str(row[0]),
                OfficialIdentity(
                    str(row[1]),
                    cast("ActorKind", str(row[2])),
                    str(row[3]),
                    str(row[4]),
                ),
                float(row[5]),
            )
            for row in rows
        )

    def _for_official_sync(
        self,
        official: OfficialIdentity,
    ) -> CrossPlatformIdentityLink | None:
        official = canonical_official_identity(official)
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
        official = canonical_official_identity(official)
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


def _official_values(identity: OfficialIdentity) -> tuple[str, str, str, str]:
    return (
        identity.app_id,
        identity.kind,
        identity.openid,
        identity.scope_id,
    )


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
