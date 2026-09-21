# SPDX-License-Identifier: MIT
"""Platform-neutral persistence for team resource subscriptions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

from ironsbot.core.platform import (
    ActorPrincipal,
    ActorRef,
    ConversationPrincipal,
    ConversationRef,
)
from ironsbot.integrations.storage.conversation_principal_rows import (
    PrincipalRowMergeSpec,
    delete_principal_rows,
    merge_latest_principal_rows,
)
from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    require_sqlite_columns,
)
from ironsbot.services.identity_principals import (
    default_actor_principal,
    default_conversation_principal,
)
from ironsbot.services.team.resource_subscriptions import (
    TeamResourcePrivateSubscription,
    TeamResourcePrivateSubscriptionUpdate,
    TeamResourceSubscription,
    TeamResourceSubscriptionPrompt,
    TeamResourceSubscriptionUpdate,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path
    from typing import Any

    from ironsbot.core.platform import ConversationPrincipalKind

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS team_resource_subscriptions (
        conversation_platform TEXT NOT NULL,
        conversation_account_id TEXT NOT NULL DEFAULT '',
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        team_id INTEGER NOT NULL,
        team_name TEXT NOT NULL DEFAULT '',
        threshold INTEGER NOT NULL,
        created_by_platform TEXT NOT NULL,
        created_by_account_id TEXT NOT NULL DEFAULT '',
        created_by_kind TEXT NOT NULL,
        created_by_id TEXT NOT NULL,
        created_by_scope_id TEXT NOT NULL DEFAULT '',
        updated_by_platform TEXT NOT NULL,
        updated_by_account_id TEXT NOT NULL DEFAULT '',
        updated_by_kind TEXT NOT NULL,
        updated_by_id TEXT NOT NULL,
        updated_by_scope_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (
            conversation_platform, conversation_account_id, conversation_kind,
            conversation_id, team_id
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS team_resource_subscription_mentions (
        conversation_platform TEXT NOT NULL,
        conversation_account_id TEXT NOT NULL DEFAULT '',
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        team_id INTEGER NOT NULL,
        actor_platform TEXT NOT NULL,
        actor_account_id TEXT NOT NULL DEFAULT '',
        actor_kind TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        actor_scope_id TEXT NOT NULL DEFAULT '',
        position INTEGER NOT NULL,
        PRIMARY KEY (
            conversation_platform, conversation_account_id, conversation_kind,
            conversation_id, team_id, actor_platform, actor_account_id,
            actor_kind, actor_id, actor_scope_id
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS team_resource_private_subscriptions (
        actor_platform TEXT NOT NULL,
        actor_account_id TEXT NOT NULL DEFAULT '',
        actor_kind TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        actor_scope_id TEXT NOT NULL DEFAULT '',
        team_id INTEGER NOT NULL,
        team_name TEXT NOT NULL DEFAULT '',
        threshold INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (
            actor_platform, actor_account_id, actor_kind, actor_id,
            actor_scope_id, team_id
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS team_resource_subscription_prompts (
        conversation_platform TEXT NOT NULL,
        conversation_account_id TEXT NOT NULL DEFAULT '',
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        team_id INTEGER NOT NULL,
        team_name TEXT NOT NULL DEFAULT '',
        prompted_by_platform TEXT NOT NULL,
        prompted_by_account_id TEXT NOT NULL DEFAULT '',
        prompted_by_kind TEXT NOT NULL,
        prompted_by_id TEXT NOT NULL,
        prompted_by_scope_id TEXT NOT NULL DEFAULT '',
        prompted_at TEXT NOT NULL,
        handled_by_platform TEXT,
        handled_by_account_id TEXT,
        handled_by_kind TEXT,
        handled_by_id TEXT,
        handled_by_scope_id TEXT,
        handled_at TEXT,
        accepted INTEGER,
        PRIMARY KEY (
            conversation_platform, conversation_account_id, conversation_kind,
            conversation_id
        )
    )
    """,
)
_PRINCIPAL_SCHEMA = (
    """
    CREATE TABLE team_resource_subscriptions_v3 (
        principal_kind TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        conversation_platform TEXT NOT NULL,
        conversation_account_id TEXT NOT NULL DEFAULT '',
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        team_id INTEGER NOT NULL,
        team_name TEXT NOT NULL DEFAULT '',
        threshold INTEGER NOT NULL,
        created_by_platform TEXT NOT NULL,
        created_by_account_id TEXT NOT NULL DEFAULT '',
        created_by_kind TEXT NOT NULL,
        created_by_id TEXT NOT NULL,
        created_by_scope_id TEXT NOT NULL DEFAULT '',
        updated_by_platform TEXT NOT NULL,
        updated_by_account_id TEXT NOT NULL DEFAULT '',
        updated_by_kind TEXT NOT NULL,
        updated_by_id TEXT NOT NULL,
        updated_by_scope_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (principal_kind, principal_id, team_id)
    )
    """,
    """
    CREATE TABLE team_resource_subscription_mentions_v3 (
        principal_kind TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        team_id INTEGER NOT NULL,
        actor_platform TEXT NOT NULL,
        actor_account_id TEXT NOT NULL DEFAULT '',
        actor_kind TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        actor_scope_id TEXT NOT NULL DEFAULT '',
        position INTEGER NOT NULL,
        PRIMARY KEY (
            principal_kind, principal_id, team_id,
            actor_platform, actor_account_id, actor_kind, actor_id, actor_scope_id
        )
    )
    """,
    """
    CREATE TABLE team_resource_private_subscriptions_v3 (
        principal_kind TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        actor_platform TEXT NOT NULL,
        actor_account_id TEXT NOT NULL DEFAULT '',
        actor_kind TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        actor_scope_id TEXT NOT NULL DEFAULT '',
        team_id INTEGER NOT NULL,
        team_name TEXT NOT NULL DEFAULT '',
        threshold INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (principal_kind, principal_id, team_id)
    )
    """,
    """
    CREATE TABLE team_resource_subscription_prompts_v3 (
        principal_kind TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        conversation_platform TEXT NOT NULL,
        conversation_account_id TEXT NOT NULL DEFAULT '',
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        team_id INTEGER NOT NULL,
        team_name TEXT NOT NULL DEFAULT '',
        prompted_by_platform TEXT NOT NULL,
        prompted_by_account_id TEXT NOT NULL DEFAULT '',
        prompted_by_kind TEXT NOT NULL,
        prompted_by_id TEXT NOT NULL,
        prompted_by_scope_id TEXT NOT NULL DEFAULT '',
        prompted_at TEXT NOT NULL,
        handled_by_platform TEXT,
        handled_by_account_id TEXT,
        handled_by_kind TEXT,
        handled_by_id TEXT,
        handled_by_scope_id TEXT,
        handled_at TEXT,
        accepted INTEGER,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (principal_kind, principal_id)
    )
    """,
)
_PRIVATE_MERGE = PrincipalRowMergeSpec(
    table="team_resource_private_subscriptions",
    value_columns=(
        "actor_platform",
        "actor_account_id",
        "actor_kind",
        "actor_id",
        "actor_scope_id",
        "team_id",
        "team_name",
        "threshold",
        "created_at",
        "updated_at",
    ),
    identity_columns=("team_id",),
    order_columns=("updated_at",),
)
_PROMPT_MERGE = PrincipalRowMergeSpec(
    table="team_resource_subscription_prompts",
    value_columns=(
        "conversation_platform",
        "conversation_account_id",
        "conversation_kind",
        "conversation_id",
        "team_id",
        "team_name",
        "prompted_by_platform",
        "prompted_by_account_id",
        "prompted_by_kind",
        "prompted_by_id",
        "prompted_by_scope_id",
        "prompted_at",
        "handled_by_platform",
        "handled_by_account_id",
        "handled_by_kind",
        "handled_by_id",
        "handled_by_scope_id",
        "handled_at",
        "accepted",
        "updated_at",
    ),
    identity_columns=(),
    order_columns=("updated_at",),
)


def _migrate_team_resource_principals(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(team_resource_subscriptions)"
        ).fetchall()
    }
    if "principal_kind" in columns:
        return
    for statement in _PRINCIPAL_SCHEMA:
        connection.execute(statement)
    _copy_group_subscriptions_to_principals(connection)
    _copy_group_mentions_to_principals(connection)
    _copy_private_subscriptions_to_principals(connection)
    _copy_prompts_to_principals(connection)
    for table in (
        "team_resource_subscription_mentions",
        "team_resource_subscriptions",
        "team_resource_private_subscriptions",
        "team_resource_subscription_prompts",
    ):
        connection.execute(f"DROP TABLE {table}")
        connection.execute(f"ALTER TABLE {table}_v3 RENAME TO {table}")


_MIGRATIONS = (
    SqliteMigration(1, _SCHEMA),
    SqliteMigration(
        2,
        callback=require_sqlite_columns(
            "team_resource_subscriptions",
            {
                "conversation_account_id",
                "created_by_account_id",
                "updated_by_account_id",
            },
        ),
    ),
    SqliteMigration(3, callback=_migrate_team_resource_principals),
)
MIGRATION_NAMESPACE = "team_resources"


class TeamResourceSubscriptionStore:
    def __init__(
        self,
        path: str | Path,
        *,
        conversation_principal_for: Callable[
            [ConversationRef], ConversationPrincipal
        ] = default_conversation_principal,
        actor_principal_for: Callable[[ActorRef], ActorPrincipal] = (
            default_actor_principal
        ),
    ) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )
        self._conversation_principal_for = conversation_principal_for
        self._actor_principal_for = actor_principal_for

    def list_all(self) -> list[TeamResourceSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                _GROUP_SUBSCRIPTION_SELECT
                + " ORDER BY conversation_platform, conversation_account_id, "
                "conversation_kind, conversation_id, team_id"
            ).fetchall()
            return [_subscription_from_row(conn, row) for row in rows]

    def list_conversation(
        self,
        conversation: ConversationRef,
    ) -> list[TeamResourceSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                _GROUP_SUBSCRIPTION_SELECT
                + """
                WHERE principal_kind = ? AND principal_id = ?
                ORDER BY team_id
                """,
                self._conversation_owner_values(conversation),
            ).fetchall()
            return [_subscription_from_row(conn, row) for row in rows]

    def upsert(self, update: TeamResourceSubscriptionUpdate) -> None:
        conversation_values = _conversation_values(update.conversation)
        owner_values = self._conversation_owner_values(update.conversation)
        operator_values = _actor_values(update.operator)
        now = _now_text()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO team_resource_subscriptions (
                    principal_kind, principal_id,
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id,
                    team_id, team_name, threshold,
                    created_by_platform, created_by_account_id, created_by_kind,
                    created_by_id, created_by_scope_id,
                    updated_by_platform, updated_by_account_id, updated_by_kind,
                    updated_by_id, updated_by_scope_id, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(principal_kind, principal_id, team_id) DO UPDATE SET
                    conversation_platform = excluded.conversation_platform,
                    conversation_account_id = excluded.conversation_account_id,
                    conversation_kind = excluded.conversation_kind,
                    conversation_id = excluded.conversation_id,
                    team_name = excluded.team_name,
                    threshold = excluded.threshold,
                    updated_by_platform = excluded.updated_by_platform,
                    updated_by_account_id = excluded.updated_by_account_id,
                    updated_by_kind = excluded.updated_by_kind,
                    updated_by_id = excluded.updated_by_id,
                    updated_by_scope_id = excluded.updated_by_scope_id,
                    updated_at = excluded.updated_at
                """,
                (
                    *owner_values,
                    *conversation_values,
                    update.team_id,
                    update.team_name.strip(),
                    update.threshold,
                    *operator_values,
                    *operator_values,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                DELETE FROM team_resource_subscription_mentions
                WHERE principal_kind = ? AND principal_id = ? AND team_id = ?
                """,
                (*owner_values, update.team_id),
            )
            _insert_mentions(
                conn,
                self._conversation_principal_for(update.conversation),
                update.team_id,
                update.mention_actors,
            )

    def list_all_private(self) -> list[TeamResourcePrivateSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT actor_platform, actor_account_id, actor_kind, actor_id,
                       actor_scope_id,
                       team_id, team_name, threshold, created_at, updated_at
                FROM team_resource_private_subscriptions
                ORDER BY actor_platform, actor_account_id, actor_kind, actor_id,
                         actor_scope_id, team_id
                """
            ).fetchall()
        return [_private_subscription_from_row(row) for row in rows]

    def list_actor(self, actor: ActorRef) -> list[TeamResourcePrivateSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT actor_platform, actor_account_id, actor_kind, actor_id,
                       actor_scope_id,
                       team_id, team_name, threshold, created_at, updated_at
                FROM team_resource_private_subscriptions
                WHERE principal_kind = ? AND principal_id = ?
                ORDER BY team_id
                """,
                self._actor_owner_values(actor),
            ).fetchall()
        return [_private_subscription_from_row(row) for row in rows]

    def upsert_private(self, update: TeamResourcePrivateSubscriptionUpdate) -> None:
        now = _now_text()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO team_resource_private_subscriptions (
                    principal_kind, principal_id,
                    actor_platform, actor_account_id, actor_kind, actor_id,
                    actor_scope_id,
                    team_id, team_name, threshold, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(principal_kind, principal_id, team_id) DO UPDATE SET
                    actor_platform = excluded.actor_platform,
                    actor_account_id = excluded.actor_account_id,
                    actor_kind = excluded.actor_kind,
                    actor_id = excluded.actor_id,
                    actor_scope_id = excluded.actor_scope_id,
                    team_name = excluded.team_name,
                    threshold = excluded.threshold,
                    updated_at = excluded.updated_at
                """,
                (
                    *self._actor_owner_values(update.actor),
                    *_actor_values(update.actor),
                    update.team_id,
                    update.team_name.strip(),
                    update.threshold,
                    now,
                    now,
                ),
            )

    def has_prompted_conversation(self, conversation: ConversationRef) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM team_resource_subscription_prompts
                WHERE principal_kind = ? AND principal_id = ?
                """,
                self._conversation_owner_values(conversation),
            ).fetchone()
        return row is not None

    def get_pending_prompt(
        self,
        conversation: ConversationRef,
    ) -> TeamResourceSubscriptionPrompt | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT conversation_platform, conversation_account_id,
                       conversation_kind, conversation_id, team_id, team_name,
                       prompted_by_platform, prompted_by_account_id,
                       prompted_by_kind, prompted_by_id, prompted_by_scope_id,
                       prompted_at, handled_by_platform, handled_by_account_id,
                       handled_by_kind, handled_by_id, handled_by_scope_id,
                       handled_at, accepted
                FROM team_resource_subscription_prompts
                WHERE principal_kind = ? AND principal_id = ?
                  AND handled_at IS NULL
                """,
                self._conversation_owner_values(conversation),
            ).fetchone()
        return _prompt_from_row(row) if row is not None else None

    def mark_conversation_prompted(
        self,
        *,
        conversation: ConversationRef,
        team_id: int,
        team_name: str,
        prompted_by: ActorRef,
    ) -> None:
        now = _now_text()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO team_resource_subscription_prompts (
                    principal_kind, principal_id,
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id, team_id, team_name,
                    prompted_by_platform, prompted_by_account_id,
                    prompted_by_kind, prompted_by_id, prompted_by_scope_id,
                    prompted_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    *self._conversation_owner_values(conversation),
                    *_conversation_values(conversation),
                    team_id,
                    team_name.strip(),
                    *_actor_values(prompted_by),
                    now,
                    now,
                ),
            )

    def mark_prompt_handled(
        self,
        *,
        conversation: ConversationRef,
        handled_by: ActorRef,
        accepted: bool,
    ) -> None:
        now = _now_text()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE team_resource_subscription_prompts
                SET handled_by_platform = ?, handled_by_account_id = ?,
                    handled_by_kind = ?, handled_by_id = ?,
                    handled_by_scope_id = ?, handled_at = ?, accepted = ?,
                    updated_at = ?
                WHERE principal_kind = ? AND principal_id = ?
                  AND handled_at IS NULL
                """,
                (
                    *_actor_values(handled_by),
                    now,
                    int(accepted),
                    now,
                    *self._conversation_owner_values(conversation),
                ),
            )

    def update_team_name(
        self,
        *,
        conversation: ConversationRef,
        team_id: int,
        team_name: str,
    ) -> None:
        if not team_name.strip():
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE team_resource_subscriptions
                SET team_name = ?, updated_at = ?
                WHERE principal_kind = ? AND principal_id = ? AND team_id = ?
                """,
                (
                    team_name.strip(),
                    _now_text(),
                    *self._conversation_owner_values(conversation),
                    team_id,
                ),
            )

    def delete(self, *, conversation: ConversationRef, team_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM team_resource_subscriptions
                WHERE principal_kind = ? AND principal_id = ? AND team_id = ?
                """,
                (*self._conversation_owner_values(conversation), team_id),
            )
            conn.execute(
                """
                DELETE FROM team_resource_subscription_mentions
                WHERE principal_kind = ? AND principal_id = ? AND team_id = ?
                """,
                (*self._conversation_owner_values(conversation), team_id),
            )
            return cursor.rowcount > 0

    def update_private_team_name(
        self,
        *,
        actor: ActorRef,
        team_id: int,
        team_name: str,
    ) -> None:
        if not team_name.strip():
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE team_resource_private_subscriptions
                SET team_name = ?, updated_at = ?
                WHERE principal_kind = ? AND principal_id = ? AND team_id = ?
                """,
                (
                    team_name.strip(),
                    _now_text(),
                    *self._actor_owner_values(actor),
                    team_id,
                ),
            )

    def delete_private(self, *, actor: ActorRef, team_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM team_resource_private_subscriptions
                WHERE principal_kind = ? AND principal_id = ? AND team_id = ?
                """,
                (*self._actor_owner_values(actor), team_id),
            )
            return cursor.rowcount > 0

    def merge_conversation_principals(
        self,
        source: ConversationPrincipal,
        target: ConversationPrincipal,
    ) -> None:
        if source == target:
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _merge_group_subscriptions(connection, source, target)
            merge_latest_principal_rows(
                connection,
                _PROMPT_MERGE,
                source=source,
                target=target,
            )

    def merge_actor_principals(
        self,
        source: ActorPrincipal,
        target: ActorPrincipal,
    ) -> None:
        if source == target:
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            merge_latest_principal_rows(
                connection,
                _PRIVATE_MERGE,
                source=source,
                target=target,
            )

    def _conversation_owner_values(
        self,
        conversation: ConversationRef,
    ) -> tuple[str, str]:
        principal = self._conversation_principal_for(conversation)
        return principal.kind, principal.id

    def _actor_owner_values(self, actor: ActorRef) -> tuple[str, str]:
        principal = self._actor_principal_for(actor)
        return principal.kind, principal.id

    def _connect(self) -> AbstractContextManager[sqlite3.Connection]:
        return self._database.connect()


_GROUP_SUBSCRIPTION_SELECT = """
    SELECT principal_kind, principal_id,
           conversation_platform, conversation_account_id, conversation_kind,
           conversation_id, team_id, team_name, threshold,
           created_by_platform, created_by_account_id, created_by_kind,
           created_by_id, created_by_scope_id,
           updated_by_platform, updated_by_account_id, updated_by_kind,
           updated_by_id, updated_by_scope_id, created_at, updated_at
    FROM team_resource_subscriptions
"""


def _subscription_from_row(
    connection: Any,
    row: tuple[Any, ...],
) -> TeamResourceSubscription:
    owner = ConversationPrincipal(
        cast("ConversationPrincipalKind", str(row[0])),
        str(row[1]),
    )
    conversation = ConversationIdentityColumns(*row[2:6]).to_conversation()
    created_by = ActorIdentityColumns(*row[9:14]).to_actor()
    updated_by = ActorIdentityColumns(*row[14:19]).to_actor()
    return TeamResourceSubscription(
        conversation=conversation,
        team_id=int(row[6]),
        team_name=str(row[7] or ""),
        threshold=int(row[8]),
        mention_actors=_mention_actors(connection, owner, int(row[6])),
        created_by=created_by,
        updated_by=updated_by,
        created_at=str(row[19]),
        updated_at=str(row[20]),
    )


def _private_subscription_from_row(
    row: tuple[Any, ...],
) -> TeamResourcePrivateSubscription:
    return TeamResourcePrivateSubscription(
        actor=ActorIdentityColumns(*row[:5]).to_actor(),
        team_id=int(row[5]),
        team_name=str(row[6] or ""),
        threshold=int(row[7]),
        created_at=str(row[8]),
        updated_at=str(row[9]),
    )


def _prompt_from_row(row: tuple[Any, ...]) -> TeamResourceSubscriptionPrompt:
    handled_by = _optional_actor(row[12:17])
    return TeamResourceSubscriptionPrompt(
        conversation=ConversationIdentityColumns(*row[:4]).to_conversation(),
        team_id=int(row[4]),
        team_name=str(row[5] or ""),
        prompted_by=ActorIdentityColumns(*row[6:11]).to_actor(),
        prompted_at=str(row[11]),
        handled_by=handled_by,
        handled_at=None if row[17] is None else str(row[17]),
        accepted=None if row[18] is None else bool(row[18]),
    )


def _insert_mentions(
    connection: Any,
    principal: ConversationPrincipal,
    team_id: int,
    actors: tuple[ActorRef, ...],
) -> None:
    values = [
        (
            principal.kind,
            principal.id,
            team_id,
            *_actor_values(actor),
            position,
        )
        for position, actor in enumerate(dict.fromkeys(actors))
    ]
    if values:
        connection.executemany(
            """
            INSERT INTO team_resource_subscription_mentions (
                principal_kind, principal_id, team_id,
                actor_platform, actor_account_id, actor_kind, actor_id,
                actor_scope_id, position
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )


def _mention_actors(
    connection: Any,
    principal: ConversationPrincipal,
    team_id: int,
) -> tuple[ActorRef, ...]:
    rows = connection.execute(
        """
        SELECT actor_platform, actor_account_id, actor_kind, actor_id,
               actor_scope_id
        FROM team_resource_subscription_mentions
        WHERE principal_kind = ? AND principal_id = ? AND team_id = ?
        ORDER BY position
        """,
        (principal.kind, principal.id, team_id),
    ).fetchall()
    return tuple(ActorIdentityColumns(*row).to_actor() for row in rows)


_GROUP_SUBSCRIPTION_VALUE_COLUMNS = (
    "conversation_platform",
    "conversation_account_id",
    "conversation_kind",
    "conversation_id",
    "team_id",
    "team_name",
    "threshold",
    "created_by_platform",
    "created_by_account_id",
    "created_by_kind",
    "created_by_id",
    "created_by_scope_id",
    "updated_by_platform",
    "updated_by_account_id",
    "updated_by_kind",
    "updated_by_id",
    "updated_by_scope_id",
    "created_at",
    "updated_at",
)


def _merge_group_subscriptions(
    connection: sqlite3.Connection,
    source: ConversationPrincipal,
    target: ConversationPrincipal,
) -> None:
    rows_by_owner = {
        (owner.kind, owner.id): _group_subscription_rows(connection, owner)
        for owner in (target, source)
    }
    selected: dict[
        int,
        tuple[tuple[str, str], tuple[object, ...]],
    ] = {}
    for owner in (target, source):
        owner_key = (owner.kind, owner.id)
        for row in rows_by_owner[owner_key]:
            team_id = int(str(row[4]))
            previous = selected.get(team_id)
            if previous is None or str(row[-1]) > str(previous[1][-1]):
                selected[team_id] = (owner_key, row)
    mentions = {
        (*owner_key, team_id): _raw_mentions(
            connection,
            ConversationPrincipal(
                cast("ConversationPrincipalKind", owner_key[0]),
                owner_key[1],
            ),
            team_id,
        )
        for team_id, (owner_key, _row) in selected.items()
    }
    for owner in (source, target):
        delete_principal_rows(
            connection,
            "team_resource_subscription_mentions",
            owner,
        )
        delete_principal_rows(connection, "team_resource_subscriptions", owner)
    columns = ", ".join(
        ("principal_kind", "principal_id", *_GROUP_SUBSCRIPTION_VALUE_COLUMNS)
    )
    placeholders = ", ".join(
        "?" for _ in range(len(_GROUP_SUBSCRIPTION_VALUE_COLUMNS) + 2)
    )
    for team_id, (owner_key, row) in selected.items():
        connection.execute(
            f"INSERT INTO team_resource_subscriptions ({columns}) "
            f"VALUES ({placeholders})",
            (target.kind, target.id, *row),
        )
        _insert_raw_mentions(
            connection,
            target,
            team_id,
            mentions[(*owner_key, team_id)],
        )


def _group_subscription_rows(
    connection: sqlite3.Connection,
    principal: ConversationPrincipal,
) -> list[tuple[object, ...]]:
    columns = ", ".join(_GROUP_SUBSCRIPTION_VALUE_COLUMNS)
    return [
        tuple(row)
        for row in connection.execute(
            f"SELECT {columns} FROM team_resource_subscriptions "
            "WHERE principal_kind = ? AND principal_id = ?",
            (principal.kind, principal.id),
        ).fetchall()
    ]


def _raw_mentions(
    connection: sqlite3.Connection,
    principal: ConversationPrincipal,
    team_id: int,
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in connection.execute(
            """
            SELECT actor_platform, actor_account_id, actor_kind, actor_id,
                   actor_scope_id, position
            FROM team_resource_subscription_mentions
            WHERE principal_kind = ? AND principal_id = ? AND team_id = ?
            ORDER BY position
            """,
            (principal.kind, principal.id, team_id),
        ).fetchall()
    )


def _insert_raw_mentions(
    connection: sqlite3.Connection,
    principal: ConversationPrincipal,
    team_id: int,
    rows: tuple[tuple[object, ...], ...],
) -> None:
    connection.executemany(
        """
        INSERT INTO team_resource_subscription_mentions (
            principal_kind, principal_id, team_id,
            actor_platform, actor_account_id, actor_kind, actor_id,
            actor_scope_id, position
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ((principal.kind, principal.id, team_id, *row) for row in rows),
    )


def _copy_group_subscriptions_to_principals(
    connection: sqlite3.Connection,
) -> None:
    rows = connection.execute(
        f"SELECT {', '.join(_GROUP_SUBSCRIPTION_VALUE_COLUMNS)} "
        "FROM team_resource_subscriptions"
    ).fetchall()
    placeholders = ", ".join(
        "?" for _ in range(len(_GROUP_SUBSCRIPTION_VALUE_COLUMNS) + 2)
    )
    for row in rows:
        conversation = ConversationIdentityColumns(
            *(str(value) for value in row[:4])
        ).to_conversation()
        principal = default_conversation_principal(conversation)
        connection.execute(
            "INSERT INTO team_resource_subscriptions_v3 VALUES "
            f"({placeholders})",
            (principal.kind, principal.id, *row),
        )


def _copy_group_mentions_to_principals(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT conversation_platform, conversation_account_id,
               conversation_kind, conversation_id, team_id,
               actor_platform, actor_account_id, actor_kind, actor_id,
               actor_scope_id, position
        FROM team_resource_subscription_mentions
        """
    ).fetchall()
    for row in rows:
        conversation = ConversationIdentityColumns(
            *(str(value) for value in row[:4])
        ).to_conversation()
        principal = default_conversation_principal(conversation)
        connection.execute(
            "INSERT INTO team_resource_subscription_mentions_v3 "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (principal.kind, principal.id, *row[4:]),
        )


def _copy_private_subscriptions_to_principals(
    connection: sqlite3.Connection,
) -> None:
    rows = connection.execute(
        """
        SELECT actor_platform, actor_account_id, actor_kind, actor_id,
               actor_scope_id, team_id, team_name, threshold, created_at,
               updated_at
        FROM team_resource_private_subscriptions
        """
    ).fetchall()
    for row in rows:
        actor = ActorIdentityColumns(*(str(value) for value in row[:5])).to_actor()
        principal = default_actor_principal(actor)
        connection.execute(
            "INSERT INTO team_resource_private_subscriptions_v3 "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (principal.kind, principal.id, *row),
        )


def _copy_prompts_to_principals(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT conversation_platform, conversation_account_id,
               conversation_kind, conversation_id, team_id, team_name,
               prompted_by_platform, prompted_by_account_id, prompted_by_kind,
               prompted_by_id, prompted_by_scope_id, prompted_at,
               handled_by_platform, handled_by_account_id, handled_by_kind,
               handled_by_id, handled_by_scope_id, handled_at, accepted
        FROM team_resource_subscription_prompts
        """
    ).fetchall()
    for row in rows:
        conversation = ConversationIdentityColumns(
            *(str(value) for value in row[:4])
        ).to_conversation()
        principal = default_conversation_principal(conversation)
        updated_at = str(row[17] or row[11])
        connection.execute(
            "INSERT INTO team_resource_subscription_prompts_v3 VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (principal.kind, principal.id, *row, updated_at),
        )


def _conversation_values(conversation: ConversationRef) -> tuple[str, str, str, str]:
    return ConversationIdentityColumns.from_conversation(conversation).values()


def _actor_values(actor: ActorRef) -> tuple[str, str, str, str, str]:
    return ActorIdentityColumns.from_actor(actor).values()


def _optional_actor(values: tuple[Any, ...]) -> ActorRef | None:
    if all(value is None for value in values):
        return None
    return ActorIdentityColumns(*values).to_actor()


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()
