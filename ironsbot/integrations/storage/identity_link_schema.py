# SPDX-License-Identifier: MIT
"""SQLite schema for explicit cross-platform identity links."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import SqliteMigration

if TYPE_CHECKING:
    import sqlite3

IDENTITY_LINK_MIGRATIONS = (
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
    SqliteMigration(
        2,
        callback=lambda connection: _canonicalize_member_links(connection),  # noqa: PLW0108
    ),
    SqliteMigration(
        3,
        statements=(
            """
            CREATE TABLE cross_platform_group_links (
                official_app_id TEXT NOT NULL,
                official_group_openid TEXT NOT NULL,
                onebot_group_id TEXT NOT NULL,
                linked_at REAL NOT NULL,
                PRIMARY KEY (official_app_id, official_group_openid),
                UNIQUE (official_app_id, onebot_group_id)
            )
            """,
        ),
    ),
    SqliteMigration(
        4,
        statements=(
            """
            CREATE TABLE official_union_identities (
                official_app_id TEXT NOT NULL,
                official_kind TEXT NOT NULL
                    CHECK (official_kind IN ('member', 'user')),
                official_openid TEXT NOT NULL,
                official_scope_id TEXT NOT NULL DEFAULT '',
                union_openid TEXT NOT NULL DEFAULT '',
                union_user_account TEXT NOT NULL DEFAULT '',
                observed_at REAL NOT NULL,
                PRIMARY KEY (
                    official_app_id, official_kind,
                    official_openid, official_scope_id
                ),
                CHECK (union_openid <> '' OR union_user_account <> '')
            )
            """,
            """
            CREATE INDEX official_union_identities_openid
            ON official_union_identities (union_openid)
            WHERE union_openid <> ''
            """,
            """
            CREATE INDEX official_union_identities_account
            ON official_union_identities (union_user_account)
            WHERE union_user_account <> ''
            """,
        ),
    ),
)


def _canonicalize_member_links(connection: sqlite3.Connection) -> None:
    conflicts = connection.execute(
        """
        SELECT official_app_id, official_openid
        FROM cross_platform_identity_links
        WHERE official_kind = 'member'
        GROUP BY official_app_id, official_openid
        HAVING COUNT(DISTINCT onebot_qq_id) > 1
        """
    ).fetchall()
    if conflicts:
        msg = (
            "conflicting group-scoped identity links prevent canonical member migration"
        )
        raise RuntimeError(msg)
    connection.execute(
        """
        CREATE TABLE cross_platform_identity_links_v2 (
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
        """
    )
    connection.execute(
        """
        INSERT INTO cross_platform_identity_links_v2 (
            official_app_id, official_kind, official_openid,
            official_scope_id, onebot_qq_id, linked_at
        )
        SELECT official_app_id, official_kind, official_openid,
               CASE WHEN official_kind = 'member' THEN '' ELSE official_scope_id END,
               onebot_qq_id, MAX(linked_at)
        FROM cross_platform_identity_links
        GROUP BY official_app_id, official_kind, official_openid,
                 CASE WHEN official_kind = 'member' THEN '' ELSE official_scope_id END,
                 onebot_qq_id
        """
    )
    connection.execute("DROP TABLE cross_platform_identity_links")
    connection.execute(
        "ALTER TABLE cross_platform_identity_links_v2 "
        "RENAME TO cross_platform_identity_links"
    )
    connection.execute(
        """
        CREATE INDEX cross_platform_identity_links_onebot
        ON cross_platform_identity_links (onebot_qq_id, official_app_id)
        """
    )
