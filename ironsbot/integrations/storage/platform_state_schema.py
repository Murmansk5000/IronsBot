# SPDX-License-Identifier: MIT
"""Target schemas and row conversion for platform-neutral state identities.

Only the offline platform-state migration imports this module. Runtime
repositories get their own narrow table APIs after the migration is enabled.
"""

from __future__ import annotations

from contextlib import closing
from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, Platform
from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.platform_state_copy import (
    contains_platform_identities,
    copy_platform_identity_tables,
)
from ironsbot.integrations.storage.platform_state_copy_helpers import (
    copy_raw_rows,
    identity_text,
    legacy_conversation,
    onebot_actor,
    onebot_group,
    read_state,
    state_rows,
    state_table_exists,
)
from ironsbot.integrations.storage.platform_state_legacy_copy import (
    copy_legacy_conversation_preferences,
    copy_legacy_lucky_skin_preferences,
    copy_legacy_player_bindings,
    copy_legacy_player_query_usage,
    copy_legacy_rank_display_limits,
    copy_legacy_team_resources,
)
from ironsbot.integrations.storage.platform_state_platform_copy import (
    copy_platform_conversation_preferences,
    copy_platform_lucky_skin_preferences,
    copy_platform_player_bindings,
    copy_platform_player_query_usage,
    copy_platform_rank_display_limits,
    copy_platform_team_resources,
    platform_actor_from_row,
)
from ironsbot.services.identity_principals import default_actor_principal

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

QQ_IDENTITY_TABLES = frozenset(
    {
        "bili_push_category_preferences",
        "bili_push_preferences",
        "group_rank_display_limits",
        "lucky_skin_watch_preferences",
        "player_bindings",
        "player_query_usage",
        "push_daily_hints",
        "push_time_preferences",
        "push_unsubscriptions",
        "team_resource_private_subscriptions",
        "team_resource_subscription_mentions",
        "team_resource_subscription_prompts",
        "team_resource_subscriptions",
    }
)
RUNTIME_IDENTITY_TABLES = frozenset({"pending_team_audit_reminders"})
AI_IDENTITY_TABLES = frozenset({"messages"})

_ACTOR_COLUMNS = """
    actor_platform TEXT NOT NULL,
    actor_account_id TEXT NOT NULL DEFAULT '',
    actor_kind TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_scope_id TEXT NOT NULL DEFAULT ''
"""
_CONVERSATION_COLUMNS = """
    conversation_platform TEXT NOT NULL,
    conversation_account_id TEXT NOT NULL DEFAULT '',
    conversation_kind TEXT NOT NULL,
    conversation_id TEXT NOT NULL
"""


def create_qq_state_schema(connection: sqlite3.Connection) -> None:
    """Create target tables for all QQ user and group state."""

    statements = (
        """
        CREATE TABLE player_bindings (
            principal_kind TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            player_id INTEGER,
            player_nick TEXT,
            choice_completed INTEGER NOT NULL DEFAULT 0,
            last_changed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (principal_kind, principal_id)
        )
        """,
        """
        CREATE TABLE player_query_usage (
            local_date TEXT NOT NULL,
            principal_kind TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            action_key TEXT NOT NULL,
            usage_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (
                local_date, principal_kind, principal_id,
                scope, player_id, action_key
            )
        )
        """,
        """
        CREATE TABLE lucky_skin_watch_preferences (
            principal_kind TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            skin_ids_json TEXT NOT NULL,
            initialized_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (principal_kind, principal_id)
        )
        """,
        f"""
        CREATE TABLE push_unsubscriptions (
            principal_kind TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            {_CONVERSATION_COLUMNS},
            subscription_key TEXT NOT NULL,
            feature TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (principal_kind, principal_id, subscription_key)
        )
        """,
        f"""
        CREATE TABLE push_time_preferences (
            principal_kind TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            {_CONVERSATION_COLUMNS},
            subscription_key TEXT NOT NULL,
            preference_type TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (
                principal_kind, principal_id, subscription_key, preference_type
            )
        )
        """,
        f"""
        CREATE TABLE push_daily_hints (
            principal_kind TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            {_CONVERSATION_COLUMNS},
            hint_key TEXT NOT NULL,
            delivered_on TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (principal_kind, principal_id, hint_key)
        )
        """,
        f"""
        CREATE TABLE bili_push_preferences (
            principal_kind TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            {_CONVERSATION_COLUMNS},
            uid INTEGER NOT NULL,
            mode TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (principal_kind, principal_id, uid)
        )
        """,
        f"""
        CREATE TABLE bili_push_category_preferences (
            principal_kind TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            {_CONVERSATION_COLUMNS},
            uid INTEGER NOT NULL,
            category TEXT NOT NULL,
            muted INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (principal_kind, principal_id, uid, category)
        )
        """,
        f"""
        CREATE TABLE group_rank_display_limits (
            principal_kind TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            {_CONVERSATION_COLUMNS},
            display_limit INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by_platform TEXT NOT NULL,
            updated_by_account_id TEXT NOT NULL DEFAULT '',
            updated_by_kind TEXT NOT NULL,
            updated_by_id TEXT NOT NULL,
            updated_by_scope_id TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (principal_kind, principal_id)
        )
        """,
        f"""
        CREATE TABLE team_resource_subscriptions (
            principal_kind TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            {_CONVERSATION_COLUMNS},
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
        f"""
        CREATE TABLE team_resource_subscription_mentions (
            principal_kind TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            team_id INTEGER NOT NULL,
            {_ACTOR_COLUMNS},
            position INTEGER NOT NULL,
            PRIMARY KEY (
                principal_kind, principal_id, team_id,
                actor_platform, actor_account_id, actor_kind, actor_id,
                actor_scope_id
            )
        )
        """,
        f"""
        CREATE TABLE team_resource_private_subscriptions (
            principal_kind TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            {_ACTOR_COLUMNS},
            team_id INTEGER NOT NULL,
            team_name TEXT NOT NULL DEFAULT '',
            threshold INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (principal_kind, principal_id, team_id)
        )
        """,
        f"""
        CREATE TABLE team_resource_subscription_prompts (
            principal_kind TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            {_CONVERSATION_COLUMNS},
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
    for statement in statements:
        connection.execute(statement)


def create_runtime_state_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE pending_team_audit_reminders (
            {_CONVERSATION_COLUMNS},
            {_ACTOR_COLUMNS},
            joined_at TEXT NOT NULL,
            remind_at TEXT NOT NULL,
            step INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (
                conversation_platform, conversation_account_id,
                conversation_kind, conversation_id,
                actor_platform, actor_account_id, actor_kind, actor_id,
                actor_scope_id
            )
        )
        """
    )


def create_ai_memory_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            principal_kind TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            session_key TEXT NOT NULL,
            {_CONVERSATION_COLUMNS},
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_ai_memory_principal_time
        ON messages (principal_kind, principal_id, created_at DESC)
        """
    )


def copy_qq_state(
    source: Path,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None = None,
) -> None:
    if not source.is_file():
        return
    with closing(read_state(source)) as connection:
        if contains_platform_identities(connection, QQ_IDENTITY_TABLES):
            directly_copied = QQ_IDENTITY_TABLES - {
                "bili_push_category_preferences",
                "bili_push_preferences",
                "group_rank_display_limits",
                "lucky_skin_watch_preferences",
                "player_bindings",
                "player_query_usage",
                "push_daily_hints",
                "push_time_preferences",
                "push_unsubscriptions",
                "team_resource_private_subscriptions",
                "team_resource_subscription_mentions",
                "team_resource_subscription_prompts",
                "team_resource_subscriptions",
            }
            copy_platform_identity_tables(
                connection,
                target,
                directly_copied,
                qq_official_account_id=qq_official_account_id,
            )
            copy_platform_player_bindings(
                connection,
                target,
                qq_official_account_id=qq_official_account_id,
            )
            copy_platform_player_query_usage(
                connection,
                target,
                qq_official_account_id=qq_official_account_id,
            )
            copy_platform_lucky_skin_preferences(
                connection,
                target,
                qq_official_account_id=qq_official_account_id,
            )
            copy_platform_conversation_preferences(
                connection,
                target,
                qq_official_account_id=qq_official_account_id,
            )
            copy_platform_rank_display_limits(
                connection,
                target,
                qq_official_account_id=qq_official_account_id,
            )
            copy_platform_team_resources(
                connection,
                target,
                qq_official_account_id=qq_official_account_id,
            )
            return
        copy_legacy_player_bindings(connection, target)
        copy_legacy_player_query_usage(connection, target)
        copy_legacy_lucky_skin_preferences(connection, target)
        copy_legacy_conversation_preferences(connection, target)
        copy_legacy_rank_display_limits(connection, target)
        copy_legacy_team_resources(connection, target)


def copy_runtime_state(
    source: Path,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None = None,
) -> None:
    if not source.is_file():
        return
    with closing(read_state(source)) as connection:
        if contains_platform_identities(connection, RUNTIME_IDENTITY_TABLES):
            copy_platform_identity_tables(
                connection,
                target,
                RUNTIME_IDENTITY_TABLES,
                qq_official_account_id=qq_official_account_id,
            )
            return
        for row in state_rows(connection, "pending_team_audit_reminders"):
            conversation = onebot_group(
                row["group_id"],
                "pending_team_audit_reminders",
            )
            actor = ActorRef(
                Platform.ONEBOT,
                identity_text(row["user_id"], "pending_team_audit_reminders"),
                kind="member",
                scope_id=conversation.id,
            )
            target.execute(
                "INSERT INTO pending_team_audit_reminders VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    *ConversationIdentityColumns.from_conversation(
                        conversation
                    ).values(),
                    *ActorIdentityColumns.from_actor(actor).values(),
                    row["joined_at"],
                    row["remind_at"],
                    dict(row).get("step", 1),
                ),
            )


def copy_ai_memory(
    source: Path,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None = None,
) -> None:
    if not source.is_file():
        return
    with closing(read_state(source)) as connection:
        if contains_platform_identities(connection, AI_IDENTITY_TABLES):
            _copy_platform_ai_memory(
                connection,
                target,
                qq_official_account_id=qq_official_account_id,
            )
            return
        for row in state_rows(connection, "messages"):
            actor = onebot_actor(row["user_id"], "messages")
            principal = default_actor_principal(actor)
            conversation = legacy_conversation(
                row["chat_scope"],
                row["chat_id"],
                "messages",
            )
            target.execute(
                """
                INSERT INTO messages VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    row["id"],
                    principal.kind,
                    principal.id,
                    row["session_key"],
                    *ConversationIdentityColumns.from_conversation(
                        conversation
                    ).values(),
                    row["role"],
                    row["content"],
                    row["created_at"],
                ),
            )


def _copy_platform_ai_memory(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    for row in state_rows(source, "messages"):
        if "principal_kind" in row:
            target.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(row),
            )
            continue
        principal = default_actor_principal(
            platform_actor_from_row(row, qq_official_account_id)
        )
        account_id = (
            str(row["conversation_account_id"])
            if "conversation_account_id" in row
            else (
                qq_official_account_id or ""
                if str(row["conversation_platform"]) == Platform.QQ_OFFICIAL.value
                else ""
            )
        )
        target.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                principal.kind,
                principal.id,
                row["session_key"],
                row["conversation_platform"],
                account_id,
                row["conversation_kind"],
                row["conversation_id"],
                row["role"],
                row["content"],
                row["created_at"],
            ),
        )


def copy_passthrough_tables(
    source: Path,
    target: sqlite3.Connection,
    *,
    excluded: frozenset[str],
) -> None:
    """Copy state tables without platform identities unchanged."""

    if not source.is_file():
        return
    with closing(read_state(source)) as connection:
        entries = connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
            ORDER BY type, name
            """
        ).fetchall()
        tables = [
            entry
            for entry in entries
            if entry["type"] == "table" and entry["name"] not in excluded
        ]
        for entry in tables:
            target.execute(str(entry["sql"]))
            copy_raw_rows(connection, target, str(entry["name"]))
        for entry in entries:
            if entry["type"] not in {"index", "trigger", "view"}:
                continue
            if entry["tbl_name"] not in excluded:
                target.execute(str(entry["sql"]))


def source_table_counts(source: Path, tables: frozenset[str]) -> dict[str, int]:
    if not source.is_file():
        return {}
    with closing(read_state(source)) as connection:
        return {
            table: int(
                connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            for table in tables
            if state_table_exists(connection, table)
        }


def table_exists(source: Path, table: str) -> bool:
    if not source.is_file():
        return False
    with closing(read_state(source)) as connection:
        return state_table_exists(connection, table)
