# SPDX-License-Identifier: MIT
"""Target schemas and row conversion for platform-neutral state identities.

Only the offline platform-state migration imports this module. Runtime
repositories get their own narrow table APIs after the migration is enabled.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.platform_state_copy import (
    PlatformStateDataError,
    contains_platform_identities,
    copy_platform_identity_tables,
)
from ironsbot.integrations.storage.sqlite import (
    open_sqlite_connection,
    quote_sqlite_identifier,
)
from ironsbot.services.identity_principals import (
    default_actor_principal,
    default_conversation_principal,
)

if TYPE_CHECKING:
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
    with closing(_read(source)) as connection:
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
            _copy_platform_player_bindings(
                connection,
                target,
                qq_official_account_id=qq_official_account_id,
            )
            _copy_platform_player_query_usage(
                connection,
                target,
                qq_official_account_id=qq_official_account_id,
            )
            _copy_platform_lucky_skin_preferences(
                connection,
                target,
                qq_official_account_id=qq_official_account_id,
            )
            _copy_platform_conversation_preferences(
                connection,
                target,
                qq_official_account_id=qq_official_account_id,
            )
            _copy_platform_rank_display_limits(
                connection,
                target,
                qq_official_account_id=qq_official_account_id,
            )
            _copy_platform_team_resources(
                connection,
                target,
                qq_official_account_id=qq_official_account_id,
            )
            return
        _copy_player_bindings(connection, target)
        _copy_player_query_usage(connection, target)
        _copy_lucky_skin_preferences(connection, target)
        _copy_conversation_preferences(connection, target)
        _copy_rank_display_limits(connection, target)
        _copy_team_resources(connection, target)


def copy_runtime_state(
    source: Path,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None = None,
) -> None:
    if not source.is_file():
        return
    with closing(_read(source)) as connection:
        if contains_platform_identities(connection, RUNTIME_IDENTITY_TABLES):
            copy_platform_identity_tables(
                connection,
                target,
                RUNTIME_IDENTITY_TABLES,
                qq_official_account_id=qq_official_account_id,
            )
            return
        for row in _rows(connection, "pending_team_audit_reminders"):
            conversation = _onebot_group(
                row["group_id"],
                "pending_team_audit_reminders",
            )
            actor = ActorRef(
                Platform.ONEBOT,
                _identity_text(row["user_id"], "pending_team_audit_reminders"),
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
    with closing(_read(source)) as connection:
        if contains_platform_identities(connection, AI_IDENTITY_TABLES):
            _copy_platform_ai_memory(
                connection,
                target,
                qq_official_account_id=qq_official_account_id,
            )
            return
        for row in _rows(connection, "messages"):
            actor = _onebot_actor(row["user_id"], "messages")
            principal = default_actor_principal(actor)
            conversation = _legacy_conversation(
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
    for row in _rows(source, "messages"):
        if "principal_kind" in row:
            target.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(row),
            )
            continue
        principal = default_actor_principal(
            _platform_actor_from_row(row, qq_official_account_id)
        )
        account_id = (
            str(row["conversation_account_id"])
            if "conversation_account_id" in row
            else (
                qq_official_account_id or ""
                if str(row["conversation_platform"])
                == Platform.QQ_OFFICIAL.value
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
    with closing(_read(source)) as connection:
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
            _copy_raw_rows(connection, target, str(entry["name"]))
        for entry in entries:
            if entry["type"] not in {"index", "trigger", "view"}:
                continue
            if entry["tbl_name"] not in excluded:
                target.execute(str(entry["sql"]))


def source_table_counts(source: Path, tables: frozenset[str]) -> dict[str, int]:
    if not source.is_file():
        return {}
    with closing(_read(source)) as connection:
        return {
            table: int(
                connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            for table in tables
            if _table_exists(connection, table)
        }


def table_exists(source: Path, table: str) -> bool:
    if not source.is_file():
        return False
    with closing(_read(source)) as connection:
        return _table_exists(connection, table)


def _copy_player_bindings(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    for row in _rows(source, "player_bindings"):
        actor = _onebot_actor(row["qq_user_id"], "player_bindings")
        principal = default_actor_principal(actor)
        target.execute(
            "INSERT INTO player_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                row["player_id"],
                row["player_nick"],
                row["choice_completed"],
                row["last_changed_at"],
                row["created_at"],
                row["updated_at"],
            ),
        )


def _copy_platform_player_bindings(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    for row in _rows(source, "player_bindings"):
        if "principal_kind" in row:
            target.execute(
                "INSERT INTO player_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(row),
            )
            continue
        actor = _platform_actor_from_row(row, qq_official_account_id)
        principal = default_actor_principal(actor)
        target.execute(
            "INSERT INTO player_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                row["player_id"],
                row["player_nick"],
                row["choice_completed"],
                row["last_changed_at"],
                row["created_at"],
                row["updated_at"],
            ),
        )


def _copy_platform_player_query_usage(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    for row in _rows(source, "player_query_usage"):
        if "principal_kind" in row:
            target.execute(
                "INSERT INTO player_query_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(row),
            )
            continue
        principal = default_actor_principal(
            _platform_actor_from_row(row, qq_official_account_id)
        )
        target.execute(
            "INSERT INTO player_query_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["local_date"],
                principal.kind,
                principal.id,
                row["scope"],
                row["player_id"],
                row["action_key"],
                row["usage_count"],
                row["updated_at"],
            ),
        )


def _copy_platform_lucky_skin_preferences(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    for row in _rows(source, "lucky_skin_watch_preferences"):
        if "principal_kind" in row:
            target.execute(
                "INSERT INTO lucky_skin_watch_preferences VALUES (?, ?, ?, ?, ?)",
                tuple(row),
            )
            continue
        principal = default_actor_principal(
            _platform_actor_from_row(row, qq_official_account_id)
        )
        target.execute(
            "INSERT INTO lucky_skin_watch_preferences VALUES (?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                row["skin_ids_json"],
                row["initialized_at"],
                row["updated_at"],
            ),
        )


def _copy_platform_conversation_preferences(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    table_columns = {
        "push_unsubscriptions": ("subscription_key", "feature", "created_at"),
        "push_time_preferences": (
            "subscription_key",
            "preference_type",
            "value",
            "updated_at",
        ),
        "push_daily_hints": ("hint_key", "delivered_on", "updated_at"),
        "bili_push_preferences": ("uid", "mode", "updated_at"),
        "bili_push_category_preferences": (
            "uid",
            "category",
            "muted",
            "updated_at",
        ),
    }
    for table, value_columns in table_columns.items():
        if _copy_rows_when_current(source, target, table):
            continue
        placeholders = ", ".join("?" for _ in range(6 + len(value_columns)))
        for row in _rows(source, table):
            conversation = _platform_conversation_from_row(
                row,
                qq_official_account_id,
                location=table,
            )
            principal = default_conversation_principal(conversation)
            target.execute(
                f"INSERT INTO {table} VALUES ({placeholders})",
                (
                    principal.kind,
                    principal.id,
                    *ConversationIdentityColumns.from_conversation(
                        conversation
                    ).values(),
                    *(row[column] for column in value_columns),
                ),
            )


def _copy_platform_rank_display_limits(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    table = "group_rank_display_limits"
    if _copy_rows_when_current(source, target, table):
        return
    for row in _rows(source, table):
        conversation = _platform_conversation_from_row(
            row,
            qq_official_account_id,
            location=table,
        )
        principal = default_conversation_principal(conversation)
        updated_by = _platform_actor_from_prefixed_row(
            row,
            "updated_by",
            qq_official_account_id,
            location=table,
        )
        target.execute(
            "INSERT INTO group_rank_display_limits VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                *ConversationIdentityColumns.from_conversation(conversation).values(),
                row["display_limit"],
                row["updated_at"],
                *ActorIdentityColumns.from_actor(updated_by).values(),
            ),
        )


def _copy_platform_team_resources(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    _copy_platform_team_subscriptions(
        source,
        target,
        qq_official_account_id=qq_official_account_id,
    )
    _copy_platform_team_mentions(
        source,
        target,
        qq_official_account_id=qq_official_account_id,
    )
    _copy_platform_team_private_subscriptions(
        source,
        target,
        qq_official_account_id=qq_official_account_id,
    )
    _copy_platform_team_prompts(
        source,
        target,
        qq_official_account_id=qq_official_account_id,
    )


def _copy_platform_team_subscriptions(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    table = "team_resource_subscriptions"
    if _copy_rows_when_current(source, target, table):
        return
    for row in _rows(source, table):
        conversation = _platform_conversation_from_row(
            row,
            qq_official_account_id,
            location=table,
        )
        principal = default_conversation_principal(conversation)
        created_by = _platform_actor_from_prefixed_row(
            row,
            "created_by",
            qq_official_account_id,
            location=table,
        )
        updated_by = _platform_actor_from_prefixed_row(
            row,
            "updated_by",
            qq_official_account_id,
            location=table,
        )
        target.execute(
            "INSERT INTO team_resource_subscriptions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                *ConversationIdentityColumns.from_conversation(conversation).values(),
                row["team_id"],
                row["team_name"],
                row["threshold"],
                *ActorIdentityColumns.from_actor(created_by).values(),
                *ActorIdentityColumns.from_actor(updated_by).values(),
                row["created_at"],
                row["updated_at"],
            ),
        )


def _copy_platform_team_mentions(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    table = "team_resource_subscription_mentions"
    if _copy_rows_when_current(source, target, table):
        return
    for row in _rows(source, table):
        conversation = _platform_conversation_from_row(
            row,
            qq_official_account_id,
            location=table,
        )
        principal = default_conversation_principal(conversation)
        actor = _platform_actor_from_prefixed_row(
            row,
            "actor",
            qq_official_account_id,
            location=table,
        )
        target.execute(
            "INSERT INTO team_resource_subscription_mentions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                row["team_id"],
                *ActorIdentityColumns.from_actor(actor).values(),
                row["position"],
            ),
        )


def _copy_platform_team_private_subscriptions(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    table = "team_resource_private_subscriptions"
    if _copy_rows_when_current(source, target, table):
        return
    for row in _rows(source, table):
        actor = _platform_actor_from_prefixed_row(
            row,
            "actor",
            qq_official_account_id,
            location=table,
        )
        principal = default_actor_principal(actor)
        target.execute(
            "INSERT INTO team_resource_private_subscriptions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                *ActorIdentityColumns.from_actor(actor).values(),
                row["team_id"],
                row["team_name"],
                row["threshold"],
                row["created_at"],
                row["updated_at"],
            ),
        )


def _copy_platform_team_prompts(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    table = "team_resource_subscription_prompts"
    if _copy_rows_when_current(source, target, table):
        return
    for row in _rows(source, table):
        conversation = _platform_conversation_from_row(
            row,
            qq_official_account_id,
            location=table,
        )
        principal = default_conversation_principal(conversation)
        prompted_by = _platform_actor_from_prefixed_row(
            row,
            "prompted_by",
            qq_official_account_id,
            location=table,
        )
        handled_by = _optional_platform_actor_from_prefixed_row(
            row,
            "handled_by",
            qq_official_account_id,
            location=table,
        )
        updated_at = row["handled_at"] or row["prompted_at"]
        target.execute(
            "INSERT INTO team_resource_subscription_prompts VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                *ConversationIdentityColumns.from_conversation(conversation).values(),
                row["team_id"],
                row["team_name"],
                *ActorIdentityColumns.from_actor(prompted_by).values(),
                row["prompted_at"],
                *handled_by,
                row["handled_at"],
                row["accepted"],
                updated_at,
            ),
        )


def _platform_actor_from_row(
    row: sqlite3.Row,
    qq_official_account_id: str | None,
) -> ActorRef:
    platform = str(row["actor_platform"])
    account_id = (
        str(row["actor_account_id"])
        if "actor_account_id" in row
        else (
            qq_official_account_id or ""
            if platform == Platform.QQ_OFFICIAL.value
            else ""
        )
    )
    return ActorIdentityColumns(
        platform,
        account_id,
        str(row["actor_kind"]),
        str(row["actor_id"]),
        str(row["actor_scope_id"]),
    ).to_actor()


def _platform_conversation_from_row(
    row: sqlite3.Row,
    qq_official_account_id: str | None,
    *,
    location: str,
) -> ConversationRef:
    platform = str(row["conversation_platform"])
    account_id = _platform_account_id(
        row,
        "conversation",
        platform,
        qq_official_account_id,
        location=location,
    )
    return ConversationIdentityColumns(
        platform,
        account_id,
        str(row["conversation_kind"]),
        str(row["conversation_id"]),
    ).to_conversation()


def _platform_actor_from_prefixed_row(
    row: sqlite3.Row,
    prefix: str,
    qq_official_account_id: str | None,
    *,
    location: str,
) -> ActorRef:
    platform = str(row[f"{prefix}_platform"])
    account_id = _platform_account_id(
        row,
        prefix,
        platform,
        qq_official_account_id,
        location=location,
    )
    return ActorIdentityColumns(
        platform,
        account_id,
        str(row[f"{prefix}_kind"]),
        str(row[f"{prefix}_id"]),
        str(row[f"{prefix}_scope_id"]),
    ).to_actor()


def _optional_platform_actor_from_prefixed_row(
    row: sqlite3.Row,
    prefix: str,
    qq_official_account_id: str | None,
    *,
    location: str,
) -> tuple[str | None, ...]:
    if row[f"{prefix}_platform"] is None:
        return (None, None, None, None, None)
    actor = _platform_actor_from_prefixed_row(
        row,
        prefix,
        qq_official_account_id,
        location=location,
    )
    return ActorIdentityColumns.from_actor(actor).values()


def _platform_account_id(
    row: sqlite3.Row,
    prefix: str,
    platform: str,
    qq_official_account_id: str | None,
    *,
    location: str,
) -> str:
    column = f"{prefix}_account_id"
    if column in row and row[column] not in {None, ""}:
        return str(row[column])
    if platform != Platform.QQ_OFFICIAL.value:
        return ""
    account_id = str(qq_official_account_id or "").strip()
    if not account_id:
        raise PlatformStateDataError.missing_qq_official_account_id(
            f"{location}.{column}"
        )
    return account_id


def _copy_player_query_usage(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    for row in _rows(source, "player_query_usage"):
        actor = _onebot_actor(row["qq_user_id"], "player_query_usage")
        principal = default_actor_principal(actor)
        target.execute(
            "INSERT INTO player_query_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["local_date"],
                principal.kind,
                principal.id,
                row["scope"],
                row["player_id"],
                row["action_key"],
                row["usage_count"],
                row["updated_at"],
            ),
        )


def _copy_lucky_skin_preferences(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    for row in _rows(source, "lucky_skin_watch_preferences"):
        actor = _onebot_actor(row["qq_user_id"], "lucky_skin_watch_preferences")
        principal = default_actor_principal(actor)
        target.execute(
            "INSERT INTO lucky_skin_watch_preferences VALUES (?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                row["skin_ids_json"],
                row["initialized_at"],
                row["updated_at"],
            ),
        )


def _copy_conversation_preferences(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    table_columns = {
        "push_unsubscriptions": ("subscription_key", "feature", "created_at"),
        "push_time_preferences": (
            "subscription_key",
            "preference_type",
            "value",
            "updated_at",
        ),
        "push_daily_hints": ("hint_key", "delivered_on", "updated_at"),
        "bili_push_preferences": ("uid", "mode", "updated_at"),
        "bili_push_category_preferences": (
            "uid",
            "category",
            "muted",
            "updated_at",
        ),
    }
    principal_owned = {
        "bili_push_category_preferences",
        "bili_push_preferences",
        "push_unsubscriptions",
        "push_time_preferences",
        "push_daily_hints",
    }
    for table, columns in table_columns.items():
        owner_column_count = 2 if table in principal_owned else 0
        placeholders = ", ".join(
            "?" for _ in range(owner_column_count + 4 + len(columns))
        )
        for row in _rows(source, table):
            conversation = _legacy_conversation(
                row["target_type"],
                row["target_id"],
                table,
            )
            owner = default_conversation_principal(conversation)
            target.execute(
                f"INSERT INTO {table} VALUES ({placeholders})",
                (
                    *((owner.kind, owner.id) if table in principal_owned else ()),
                    *ConversationIdentityColumns.from_conversation(
                        conversation
                    ).values(),
                    *(row[column] for column in columns),
                ),
            )


def _copy_rank_display_limits(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    for row in _rows(source, "group_rank_display_limits"):
        conversation = _onebot_group(row["group_id"], "group_rank_display_limits")
        principal = default_conversation_principal(conversation)
        actor = _onebot_actor(row["updated_by"], "group_rank_display_limits")
        target.execute(
            "INSERT INTO group_rank_display_limits VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                *ConversationIdentityColumns.from_conversation(conversation).values(),
                row["display_limit"],
                row["updated_at"],
                *ActorIdentityColumns.from_actor(actor).values(),
            ),
        )


def _copy_team_resources(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    for row in _rows(source, "team_resource_subscriptions"):
        conversation = _onebot_group(row["group_id"], "team_resource_subscriptions")
        principal = default_conversation_principal(conversation)
        created_by = _onebot_actor(row["created_by"], "team_resource_subscriptions")
        updated_by = _onebot_actor(row["updated_by"], "team_resource_subscriptions")
        target.execute(
            "INSERT INTO team_resource_subscriptions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                *ConversationIdentityColumns.from_conversation(conversation).values(),
                row["team_id"],
                row["team_name"],
                row["threshold"],
                *ActorIdentityColumns.from_actor(created_by).values(),
                *ActorIdentityColumns.from_actor(updated_by).values(),
                row["created_at"],
                row["updated_at"],
            ),
        )
        _copy_team_mentions(target, conversation, row)
    for row in _rows(source, "team_resource_private_subscriptions"):
        actor = _onebot_actor(row["user_id"], "team_resource_private_subscriptions")
        principal = default_actor_principal(actor)
        target.execute(
            "INSERT INTO team_resource_private_subscriptions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                *ActorIdentityColumns.from_actor(actor).values(),
                row["team_id"],
                row["team_name"],
                row["threshold"],
                row["created_at"],
                row["updated_at"],
            ),
        )
    _copy_team_prompts(source, target)


def _copy_team_mentions(
    target: sqlite3.Connection,
    conversation: ConversationRef,
    row: sqlite3.Row,
) -> None:
    principal = default_conversation_principal(conversation)
    for position, user_id in enumerate(_legacy_user_ids(row["at_user_ids"])):
        actor = _onebot_actor(user_id, "team_resource_subscriptions.at_user_ids")
        target.execute(
            "INSERT INTO team_resource_subscription_mentions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                row["team_id"],
                *ActorIdentityColumns.from_actor(actor).values(),
                position,
            ),
        )


def _copy_team_prompts(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    for row in _rows(source, "team_resource_subscription_prompts"):
        conversation = _onebot_group(
            row["group_id"],
            "team_resource_subscription_prompts",
        )
        prompted = _onebot_actor(
            row["prompted_by"],
            "team_resource_subscription_prompts",
        )
        handled = _optional_onebot_actor(
            row["handled_by"],
            "team_resource_subscription_prompts",
        )
        principal = default_conversation_principal(conversation)
        updated_at = row["handled_at"] or row["prompted_at"]
        target.execute(
            "INSERT INTO team_resource_subscription_prompts VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                *ConversationIdentityColumns.from_conversation(conversation).values(),
                row["team_id"],
                row["team_name"],
                *ActorIdentityColumns.from_actor(prompted).values(),
                row["prompted_at"],
                *handled,
                row["handled_at"],
                row["accepted"],
                updated_at,
            ),
        )


def _optional_onebot_actor(value: object, table: str) -> tuple[str | None, ...]:
    if value is None:
        return (None, None, None, None, None)
    return ActorIdentityColumns.from_actor(_onebot_actor(value, table)).values()


def _copy_raw_rows(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
) -> None:
    rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
    if not rows:
        return
    columns = tuple(rows[0].keys())
    table_sql = quote_sqlite_identifier(table)
    columns_sql = ", ".join(quote_sqlite_identifier(column) for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    target.executemany(
        f"INSERT INTO {table_sql} ({columns_sql}) VALUES ({placeholders})",
        (tuple(row[column] for column in columns) for row in rows),
    )


def _copy_rows_when_current(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
) -> bool:
    if not _table_exists(source, table):
        return True
    source_columns = {
        str(row[1])
        for row in source.execute(
            f"PRAGMA table_info({quote_sqlite_identifier(table)})"
        ).fetchall()
    }
    target_columns = tuple(
        str(row[1])
        for row in target.execute(
            f"PRAGMA table_info({quote_sqlite_identifier(table)})"
        ).fetchall()
    )
    if not set(target_columns).issubset(source_columns):
        return False
    rows = source.execute(
        f"SELECT * FROM {quote_sqlite_identifier(table)}"
    ).fetchall()
    if not rows:
        return True
    table_sql = quote_sqlite_identifier(table)
    columns_sql = ", ".join(
        quote_sqlite_identifier(column) for column in target_columns
    )
    placeholders = ", ".join("?" for _ in target_columns)
    target.executemany(
        f"INSERT INTO {table_sql} ({columns_sql}) VALUES ({placeholders})",
        (tuple(row[column] for column in target_columns) for row in rows),
    )
    return True


def _rows(connection: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    if not _table_exists(connection, table):
        return []
    return connection.execute(f'SELECT * FROM "{table}"').fetchall()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _read(path: Path) -> sqlite3.Connection:
    connection = open_sqlite_connection(path, read_only=True)
    connection.row_factory = sqlite3.Row
    return connection


def _legacy_conversation(
    target_type: object,
    target_id: object,
    location: str,
) -> ConversationRef:
    kind = str(target_type).strip()
    if kind not in {"private", "group"}:
        raise PlatformStateDataError.invalid_target_type(location, target_type)
    if kind == "private":
        return ConversationRef(
            Platform.ONEBOT,
            "private",
            _identity_text(target_id, location),
        )
    return ConversationRef(
        Platform.ONEBOT,
        "group",
        _identity_text(target_id, location),
    )


def _onebot_group(value: object, location: str) -> ConversationRef:
    return ConversationRef(
        Platform.ONEBOT,
        "group",
        _identity_text(value, location),
    )


def _onebot_actor(value: object, location: str) -> ActorRef:
    return ActorRef(Platform.ONEBOT, _identity_text(value, location))


def _identity_text(value: object, location: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PlatformStateDataError.empty_identity(location)
    return text


def _legacy_user_ids(value: object) -> tuple[str, ...]:
    result = [
        _identity_text(raw, "team_resource_subscriptions.at_user_ids")
        for raw in str(value or "").split(",")
        if raw.strip()
    ]
    return tuple(dict.fromkeys(result))
