# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.platform_identity import ActorIdentityColumns
from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    require_sqlite_columns,
)
from ironsbot.services.identity_principals import default_actor_principal
from ironsbot.services.seer.player_query_limits import PlayerQueryUsage

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

    from ironsbot.core.platform import ActorPrincipal, ActorRef
    from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaScope

_LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS player_query_usage (
    local_date TEXT NOT NULL,
    actor_platform TEXT NOT NULL,
    actor_account_id TEXT NOT NULL DEFAULT '',
    actor_kind TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_scope_id TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    action_key TEXT NOT NULL,
    usage_count INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (
        local_date, actor_platform, actor_account_id, actor_kind, actor_id,
        actor_scope_id, scope, player_id, action_key
    )
)
"""
_PRINCIPAL_SCHEMA = """
CREATE TABLE player_query_usage_v3 (
    local_date TEXT NOT NULL,
    principal_kind TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    action_key TEXT NOT NULL,
    usage_count INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (
        local_date, principal_kind, principal_id, scope, player_id, action_key
    )
)
"""
_MIGRATIONS = (
    SqliteMigration(1, (_LEGACY_SCHEMA,)),
    SqliteMigration(
        2,
        callback=require_sqlite_columns(
            "player_query_usage",
            {"actor_account_id"},
        ),
    ),
    SqliteMigration(
        3,
        callback=lambda connection: _migrate_to_principals(connection),  # noqa: PLW0108
    ),
)
MIGRATION_NAMESPACE = "player_query_limits"


class SqlitePlayerQueryLimitStore:
    def __init__(
        self,
        path: str | Path,
        *,
        principal_for: Callable[[ActorRef], ActorPrincipal] = default_actor_principal,
    ) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )
        self._principal_for = principal_for

    def status(  # noqa: PLR0913
        self,
        *,
        local_date: date,
        actor: ActorRef,
        scope: PlayerQueryQuotaScope,
        player_id: int,
        action_key: str,
        limit: int,
    ) -> PlayerQueryUsage:
        if limit <= 0:
            return PlayerQueryUsage(allowed=False, used_count=0, limit=limit)
        key = _usage_key(
            local_date,
            self._principal_for(actor),
            scope,
            player_id,
            action_key,
        )
        with self._database.connect() as conn:
            row = conn.execute(
                """
                SELECT usage_count FROM player_query_usage
                WHERE local_date = ? AND principal_kind = ?
                  AND principal_id = ? AND scope = ?
                  AND player_id = ? AND action_key = ?
                """,
                key,
            ).fetchone()
        used_count = 0 if row is None else int(row[0])
        return PlayerQueryUsage(
            allowed=used_count < limit,
            used_count=used_count,
            limit=limit,
        )

    def consume(  # noqa: PLR0913
        self,
        *,
        local_date: date,
        actor: ActorRef,
        scope: PlayerQueryQuotaScope,
        player_id: int,
        action_key: str,
        limit: int,
    ) -> PlayerQueryUsage:
        if limit <= 0:
            return PlayerQueryUsage(allowed=False, used_count=0, limit=limit)
        key = _usage_key(
            local_date,
            self._principal_for(actor),
            scope,
            player_id,
            action_key,
        )
        with self._database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT usage_count FROM player_query_usage
                WHERE local_date = ? AND principal_kind = ?
                  AND principal_id = ? AND scope = ?
                  AND player_id = ? AND action_key = ?
                """,
                key,
            ).fetchone()
            used_count = 0 if row is None else int(row[0])
            if used_count >= limit:
                return PlayerQueryUsage(
                    allowed=False,
                    used_count=used_count,
                    limit=limit,
                )
            next_count = used_count + 1
            conn.execute(
                """
                INSERT INTO player_query_usage (
                    local_date, principal_kind, principal_id, scope,
                    player_id, action_key, usage_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    local_date, principal_kind, principal_id,
                    scope, player_id, action_key
                ) DO UPDATE SET
                    usage_count = excluded.usage_count,
                    updated_at = excluded.updated_at
                """,
                (*key, next_count, _utc_now()),
            )
        return PlayerQueryUsage(
            allowed=True,
            used_count=next_count,
            limit=limit,
        )

    def merge_principals(
        self,
        source: ActorPrincipal,
        target: ActorPrincipal,
    ) -> None:
        if source == target:
            return
        with self._database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT local_date, scope, player_id, action_key,
                       usage_count, updated_at
                FROM player_query_usage
                WHERE principal_kind = ? AND principal_id = ?
                """,
                _principal_values(source),
            ).fetchall()
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO player_query_usage (
                        local_date, principal_kind, principal_id, scope,
                        player_id, action_key, usage_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (
                        local_date, principal_kind, principal_id,
                        scope, player_id, action_key
                    ) DO UPDATE SET
                        usage_count = player_query_usage.usage_count
                            + excluded.usage_count,
                        updated_at = MAX(
                            player_query_usage.updated_at,
                            excluded.updated_at
                        )
                    """,
                    (row[0], *_principal_values(target), *row[1:]),
                )
            conn.execute(
                "DELETE FROM player_query_usage "
                "WHERE principal_kind = ? AND principal_id = ?",
                _principal_values(source),
            )


def _migrate_to_principals(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(player_query_usage)"
        ).fetchall()
    }
    if "principal_kind" in columns:
        return
    connection.execute(_PRINCIPAL_SCHEMA)
    rows = connection.execute(
        """
        SELECT local_date, actor_platform, actor_account_id, actor_kind,
               actor_id, actor_scope_id, scope, player_id, action_key,
               usage_count, updated_at
        FROM player_query_usage
        """
    ).fetchall()
    for row in rows:
        actor = ActorIdentityColumns(
            str(row[1]), str(row[2]), str(row[3]), str(row[4]), str(row[5])
        ).to_actor()
        principal = default_actor_principal(actor)
        connection.execute(
            """
            INSERT INTO player_query_usage_v3 (
                local_date, principal_kind, principal_id, scope,
                player_id, action_key, usage_count, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row[0], *_principal_values(principal), *row[6:]),
        )
    connection.execute("DROP TABLE player_query_usage")
    connection.execute(
        "ALTER TABLE player_query_usage_v3 RENAME TO player_query_usage"
    )


def _usage_key(
    local_date: date,
    principal: ActorPrincipal,
    scope: PlayerQueryQuotaScope,
    player_id: int,
    action_key: str,
) -> tuple[object, ...]:
    return (
        local_date.isoformat(),
        *_principal_values(principal),
        scope,
        player_id,
        action_key,
    )


def _principal_values(principal: ActorPrincipal) -> tuple[str, str]:
    return principal.kind, principal.id


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
