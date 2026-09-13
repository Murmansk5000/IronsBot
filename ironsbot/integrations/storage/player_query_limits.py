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
from ironsbot.services.seer.player_query_limits import PlayerQueryUsage

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.platform import ActorRef
    from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaScope

_SCHEMA = """
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
_MIGRATIONS = (
    SqliteMigration(1, (_SCHEMA,)),
    SqliteMigration(
        2,
        callback=require_sqlite_columns(
            "player_query_usage",
            {"actor_account_id"},
        ),
    ),
)
MIGRATION_NAMESPACE = "player_query_limits"


class SqlitePlayerQueryLimitStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

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
        key = (
            local_date.isoformat(),
            *ActorIdentityColumns.from_actor(actor).values(),
            scope,
            player_id,
            action_key,
        )
        with self._database.connect() as conn:
            row = conn.execute(
                """
                SELECT usage_count
                FROM player_query_usage
                WHERE local_date = ? AND actor_platform = ?
                  AND actor_account_id = ? AND actor_kind = ?
                  AND actor_id = ? AND actor_scope_id = ? AND scope = ?
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

        key = (
            local_date.isoformat(),
            *ActorIdentityColumns.from_actor(actor).values(),
            scope,
            player_id,
            action_key,
        )
        with self._database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT usage_count
                FROM player_query_usage
                WHERE local_date = ? AND actor_platform = ?
                  AND actor_account_id = ? AND actor_kind = ?
                  AND actor_id = ? AND actor_scope_id = ? AND scope = ?
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
            if row is None:
                conn.execute(
                    """
                    INSERT INTO player_query_usage(
                        local_date, actor_platform, actor_account_id, actor_kind,
                        actor_id, actor_scope_id, scope, player_id,
                        action_key, usage_count, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*key, next_count, _utc_now()),
                )
            else:
                conn.execute(
                    """
                    UPDATE player_query_usage
                    SET usage_count = ?, updated_at = ?
                    WHERE local_date = ? AND actor_platform = ?
                      AND actor_account_id = ? AND actor_kind = ?
                      AND actor_id = ? AND actor_scope_id = ? AND scope = ?
                      AND player_id = ? AND action_key = ?
                    """,
                    (next_count, _utc_now(), *key),
                )
        return PlayerQueryUsage(
            allowed=True,
            used_count=next_count,
            limit=limit,
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
