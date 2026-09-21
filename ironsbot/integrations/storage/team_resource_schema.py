# SPDX-License-Identifier: MIT
"""SQLite schema and upgrades for team resource subscriptions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import (
    SqliteMigration,
    require_sqlite_columns,
)
from ironsbot.services.identity_principals import (
    default_actor_principal,
    default_conversation_principal,
)

if TYPE_CHECKING:
    import sqlite3

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


TEAM_RESOURCE_MIGRATIONS = (
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
TEAM_RESOURCE_MIGRATION_NAMESPACE = "team_resources"

GROUP_SUBSCRIPTION_VALUE_COLUMNS = (
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


def _copy_group_subscriptions_to_principals(
    connection: sqlite3.Connection,
) -> None:
    rows = connection.execute(
        f"SELECT {', '.join(GROUP_SUBSCRIPTION_VALUE_COLUMNS)} "
        "FROM team_resource_subscriptions"
    ).fetchall()
    placeholders = ", ".join(
        "?" for _ in range(len(GROUP_SUBSCRIPTION_VALUE_COLUMNS) + 2)
    )
    for row in rows:
        conversation = ConversationIdentityColumns(
            *(str(value) for value in row[:4])
        ).to_conversation()
        principal = default_conversation_principal(conversation)
        connection.execute(
            f"INSERT INTO team_resource_subscriptions_v3 VALUES ({placeholders})",
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
