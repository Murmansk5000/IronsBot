# SPDX-License-Identifier: MIT
"""Target schemas and row conversion for platform-neutral state identities.

Only the offline platform-state migration imports this module. Runtime
repositories get their own narrow table APIs after the migration is enabled.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import (
    open_sqlite_connection,
    quote_sqlite_identifier,
)

if TYPE_CHECKING:
    from pathlib import Path

QQ_IDENTITY_TABLES = frozenset(
    {
        "bili_push_preferences",
        "group_rank_display_limits",
        "lucky_skin_watch_preferences",
        "player_bindings",
        "player_query_usage",
        "push_daily_hints",
        "push_time_preferences",
        "push_unsubscriptions",
        "team_resource_private_subscriptions",
        "team_resource_subscription_prompts",
        "team_resource_subscriptions",
    }
)
RUNTIME_IDENTITY_TABLES = frozenset({"pending_team_audit_reminders"})
AI_IDENTITY_TABLES = frozenset({"messages"})

_ACTOR_COLUMNS = """
    actor_platform TEXT NOT NULL,
    actor_kind TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_scope_id TEXT NOT NULL DEFAULT ''
"""
_CONVERSATION_COLUMNS = """
    conversation_platform TEXT NOT NULL,
    conversation_kind TEXT NOT NULL,
    conversation_id TEXT NOT NULL
"""


class PlatformStateDataError(ValueError):
    """Raised for legacy rows that cannot become a platform identity."""

    @classmethod
    def invalid_target_type(
        cls,
        location: str,
        value: object,
    ) -> PlatformStateDataError:
        return cls(f"invalid target type in {location}: {value!r}")

    @classmethod
    def empty_identity(cls, location: str) -> PlatformStateDataError:
        return cls(f"empty identity in {location}")


def create_qq_state_schema(connection: sqlite3.Connection) -> None:
    """Create target tables for all QQ user and group state."""

    statements = (
        f"""
        CREATE TABLE player_bindings (
            {_ACTOR_COLUMNS},
            player_id INTEGER,
            player_nick TEXT,
            choice_completed INTEGER NOT NULL DEFAULT 0,
            last_changed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (actor_platform, actor_kind, actor_id, actor_scope_id)
        )
        """,
        f"""
        CREATE TABLE player_query_usage (
            local_date TEXT NOT NULL,
            {_ACTOR_COLUMNS},
            scope TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            action_key TEXT NOT NULL,
            usage_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (
                local_date, actor_platform, actor_kind, actor_id,
                actor_scope_id, scope, player_id, action_key
            )
        )
        """,
        f"""
        CREATE TABLE lucky_skin_watch_preferences (
            {_ACTOR_COLUMNS},
            skin_ids_json TEXT NOT NULL,
            initialized_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (actor_platform, actor_kind, actor_id, actor_scope_id)
        )
        """,
        f"""
        CREATE TABLE push_unsubscriptions (
            {_CONVERSATION_COLUMNS},
            subscription_key TEXT NOT NULL,
            feature TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (
                conversation_platform, conversation_kind, conversation_id,
                subscription_key
            )
        )
        """,
        f"""
        CREATE TABLE push_time_preferences (
            {_CONVERSATION_COLUMNS},
            subscription_key TEXT NOT NULL,
            preference_type TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (
                conversation_platform, conversation_kind, conversation_id,
                subscription_key, preference_type
            )
        )
        """,
        f"""
        CREATE TABLE push_daily_hints (
            {_CONVERSATION_COLUMNS},
            hint_key TEXT NOT NULL,
            delivered_on TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (
                conversation_platform, conversation_kind, conversation_id,
                hint_key
            )
        )
        """,
        f"""
        CREATE TABLE bili_push_preferences (
            {_CONVERSATION_COLUMNS},
            uid INTEGER NOT NULL,
            mode TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (
                conversation_platform, conversation_kind, conversation_id, uid
            )
        )
        """,
        f"""
        CREATE TABLE group_rank_display_limits (
            {_CONVERSATION_COLUMNS},
            display_limit INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by_platform TEXT NOT NULL,
            updated_by_kind TEXT NOT NULL,
            updated_by_id TEXT NOT NULL,
            updated_by_scope_id TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (conversation_platform, conversation_kind, conversation_id)
        )
        """,
        f"""
        CREATE TABLE team_resource_subscriptions (
            {_CONVERSATION_COLUMNS},
            team_id INTEGER NOT NULL,
            team_name TEXT NOT NULL DEFAULT '',
            threshold INTEGER NOT NULL,
            created_by_platform TEXT NOT NULL,
            created_by_kind TEXT NOT NULL,
            created_by_id TEXT NOT NULL,
            created_by_scope_id TEXT NOT NULL DEFAULT '',
            updated_by_platform TEXT NOT NULL,
            updated_by_kind TEXT NOT NULL,
            updated_by_id TEXT NOT NULL,
            updated_by_scope_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (
                conversation_platform, conversation_kind, conversation_id, team_id
            )
        )
        """,
        f"""
        CREATE TABLE team_resource_subscription_mentions (
            {_CONVERSATION_COLUMNS},
            team_id INTEGER NOT NULL,
            {_ACTOR_COLUMNS},
            position INTEGER NOT NULL,
            PRIMARY KEY (
                conversation_platform, conversation_kind, conversation_id, team_id,
                actor_platform, actor_kind, actor_id, actor_scope_id
            )
        )
        """,
        f"""
        CREATE TABLE team_resource_private_subscriptions (
            {_ACTOR_COLUMNS},
            team_id INTEGER NOT NULL,
            team_name TEXT NOT NULL DEFAULT '',
            threshold INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (actor_platform, actor_kind, actor_id, actor_scope_id, team_id)
        )
        """,
        f"""
        CREATE TABLE team_resource_subscription_prompts (
            {_CONVERSATION_COLUMNS},
            team_id INTEGER NOT NULL,
            team_name TEXT NOT NULL DEFAULT '',
            prompted_by_platform TEXT NOT NULL,
            prompted_by_kind TEXT NOT NULL,
            prompted_by_id TEXT NOT NULL,
            prompted_by_scope_id TEXT NOT NULL DEFAULT '',
            prompted_at TEXT NOT NULL,
            handled_by_platform TEXT,
            handled_by_kind TEXT,
            handled_by_id TEXT,
            handled_by_scope_id TEXT,
            handled_at TEXT,
            accepted INTEGER,
            PRIMARY KEY (conversation_platform, conversation_kind, conversation_id)
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
                conversation_platform, conversation_kind, conversation_id,
                actor_platform, actor_kind, actor_id, actor_scope_id
            )
        )
        """
    )


def create_ai_memory_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {_ACTOR_COLUMNS},
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
        CREATE INDEX idx_ai_memory_actor_time
        ON messages (
            actor_platform, actor_kind, actor_id, actor_scope_id, created_at DESC
        )
        """
    )


def copy_qq_state(source: Path, target: sqlite3.Connection) -> None:
    if not source.is_file():
        return
    with _read(source) as connection:
        _copy_player_bindings(connection, target)
        _copy_player_query_usage(connection, target)
        _copy_lucky_skin_preferences(connection, target)
        _copy_conversation_preferences(connection, target)
        _copy_rank_display_limits(connection, target)
        _copy_team_resources(connection, target)


def copy_runtime_state(source: Path, target: sqlite3.Connection) -> None:
    if not source.is_file():
        return
    with _read(source) as connection:
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
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    *ConversationIdentityColumns.from_conversation(conversation).values(),
                    *ActorIdentityColumns.from_actor(actor).values(),
                    row["joined_at"],
                    row["remind_at"],
                    row["step"],
                ),
            )


def copy_ai_memory(source: Path, target: sqlite3.Connection) -> None:
    if not source.is_file():
        return
    with _read(source) as connection:
        for row in _rows(connection, "messages"):
            actor = _onebot_actor(row["user_id"], "messages")
            conversation = _legacy_conversation(
                row["chat_scope"],
                row["chat_id"],
                "messages",
            )
            target.execute(
                """
                INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    *ActorIdentityColumns.from_actor(actor).values(),
                    row["session_key"],
                    *ConversationIdentityColumns.from_conversation(conversation).values(),
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
    with _read(source) as connection:
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
    with _read(source) as connection:
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
    with _read(source) as connection:
        return _table_exists(connection, table)


def _copy_player_bindings(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    for row in _rows(source, "player_bindings"):
        actor = _onebot_actor(row["qq_user_id"], "player_bindings")
        target.execute(
            "INSERT INTO player_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                *ActorIdentityColumns.from_actor(actor).values(),
                row["player_id"],
                row["player_nick"],
                row["choice_completed"],
                row["last_changed_at"],
                row["created_at"],
                row["updated_at"],
            ),
        )


def _copy_player_query_usage(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    for row in _rows(source, "player_query_usage"):
        actor = _onebot_actor(row["qq_user_id"], "player_query_usage")
        target.execute(
            "INSERT INTO player_query_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["local_date"],
                *ActorIdentityColumns.from_actor(actor).values(),
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
        target.execute(
            "INSERT INTO lucky_skin_watch_preferences VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                *ActorIdentityColumns.from_actor(actor).values(),
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
    }
    for table, columns in table_columns.items():
        placeholders = ", ".join("?" for _ in range(3 + len(columns)))
        for row in _rows(source, table):
            conversation = _legacy_conversation(
                row["target_type"],
                row["target_id"],
                table,
            )
            target.execute(
                f"INSERT INTO {table} VALUES ({placeholders})",
                (
                    *ConversationIdentityColumns.from_conversation(conversation).values(),
                    *(row[column] for column in columns),
                ),
            )


def _copy_rank_display_limits(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    for row in _rows(source, "group_rank_display_limits"):
        conversation = _onebot_group(row["group_id"], "group_rank_display_limits")
        actor = _onebot_actor(row["updated_by"], "group_rank_display_limits")
        target.execute(
            "INSERT INTO group_rank_display_limits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
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
        created_by = _onebot_actor(row["created_by"], "team_resource_subscriptions")
        updated_by = _onebot_actor(row["updated_by"], "team_resource_subscriptions")
        target.execute(
            "INSERT INTO team_resource_subscriptions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
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
        target.execute(
            "INSERT INTO team_resource_private_subscriptions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
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
    for position, user_id in enumerate(_legacy_user_ids(row["at_user_ids"])):
        actor = _onebot_actor(user_id, "team_resource_subscriptions.at_user_ids")
        target.execute(
            "INSERT INTO team_resource_subscription_mentions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                *ConversationIdentityColumns.from_conversation(conversation).values(),
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
        target.execute(
            "INSERT INTO team_resource_subscription_prompts VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                *ConversationIdentityColumns.from_conversation(conversation).values(),
                row["team_id"],
                row["team_name"],
                *ActorIdentityColumns.from_actor(prompted).values(),
                row["prompted_at"],
                *handled,
                row["handled_at"],
                row["accepted"],
            ),
        )


def _optional_onebot_actor(value: object, table: str) -> tuple[str | None, ...]:
    if value is None:
        return (None, None, None, None)
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


def _rows(connection: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    if not _table_exists(connection, table):
        return []
    return connection.execute(f'SELECT * FROM "{table}"').fetchall()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


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
