# SPDX-License-Identifier: MIT
"""Shared row conversion helpers for offline platform-state migration."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.platform_identity import ActorIdentityColumns
from ironsbot.integrations.storage.platform_state_copy import PlatformStateDataError
from ironsbot.integrations.storage.sqlite import (
    open_sqlite_connection,
    quote_sqlite_identifier,
)

if TYPE_CHECKING:
    from pathlib import Path


def optional_onebot_actor(value: object, table: str) -> tuple[str | None, ...]:
    if value is None:
        return (None, None, None, None, None)
    return ActorIdentityColumns.from_actor(onebot_actor(value, table)).values()


def copy_raw_rows(
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


def copy_rows_when_current(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
) -> bool:
    if not state_table_exists(source, table):
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
    rows = source.execute(f"SELECT * FROM {quote_sqlite_identifier(table)}").fetchall()
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


def state_rows(connection: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    if not state_table_exists(connection, table):
        return []
    return connection.execute(f'SELECT * FROM "{table}"').fetchall()


def state_table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def read_state(path: Path) -> sqlite3.Connection:
    connection = open_sqlite_connection(path, read_only=True)
    connection.row_factory = sqlite3.Row
    return connection


def legacy_conversation(
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
            identity_text(target_id, location),
        )
    return ConversationRef(
        Platform.ONEBOT,
        "group",
        identity_text(target_id, location),
    )


def onebot_group(value: object, location: str) -> ConversationRef:
    return ConversationRef(
        Platform.ONEBOT,
        "group",
        identity_text(value, location),
    )


def onebot_actor(value: object, location: str) -> ActorRef:
    return ActorRef(Platform.ONEBOT, identity_text(value, location))


def identity_text(value: object, location: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PlatformStateDataError.empty_identity(location)
    return text


def legacy_user_ids(value: object) -> tuple[str, ...]:
    result = [
        identity_text(raw, "team_resource_subscriptions.at_user_ids")
        for raw in str(value or "").split(",")
        if raw.strip()
    ]
    return tuple(dict.fromkeys(result))
