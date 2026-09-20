# SPDX-License-Identifier: MIT
"""Copy persisted platform identities into the current offline target schema."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.platform import Platform
from ironsbot.integrations.storage.sqlite import quote_sqlite_identifier

if TYPE_CHECKING:
    import sqlite3


class PlatformStateDataError(ValueError):
    """Raised for rows that cannot become an account-scoped identity."""

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

    @classmethod
    def missing_qq_official_account_id(
        cls,
        location: str,
    ) -> PlatformStateDataError:
        return cls(
            "QQ Official state requires its owning AppID during offline "
            f"migration: {location}"
        )

    @classmethod
    def missing_column(cls, table: str, column: str) -> PlatformStateDataError:
        return cls(f"missing column {table}.{column}")


def contains_platform_identities(
    connection: sqlite3.Connection,
    tables: frozenset[str],
) -> bool:
    return any(
        {"actor_platform", "conversation_platform"} & table_columns(connection, table)
        for table in tables
        if table_exists(connection, table)
    )


def copy_platform_identity_tables(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    tables: frozenset[str],
    *,
    qq_official_account_id: str | None,
) -> None:
    for table in sorted(tables):
        if not table_exists(source, table):
            continue
        source_columns = table_columns(source, table)
        if not {"actor_platform", "conversation_platform"} & source_columns:
            msg = f"mixed legacy and platform identity schema in {table}"
            raise PlatformStateDataError(msg)
        target_columns = tuple(
            str(row[1])
            for row in target.execute(
                f"PRAGMA table_info({quote_sqlite_identifier(table)})"
            ).fetchall()
        )
        rows = source.execute(
            f"SELECT * FROM {quote_sqlite_identifier(table)}"
        ).fetchall()
        if not rows:
            continue
        values = [
            tuple(
                _column_value(
                    row,
                    source_columns,
                    column,
                    table=table,
                    qq_official_account_id=qq_official_account_id,
                )
                for column in target_columns
            )
            for row in rows
        ]
        columns_sql = ", ".join(
            quote_sqlite_identifier(column) for column in target_columns
        )
        placeholders = ", ".join("?" for _ in target_columns)
        target.executemany(
            f"INSERT INTO {quote_sqlite_identifier(table)} "
            f"({columns_sql}) VALUES ({placeholders})",
            values,
        )


def _column_value(
    row: sqlite3.Row,
    source_columns: set[str],
    column: str,
    *,
    table: str,
    qq_official_account_id: str | None,
) -> object:
    if column in source_columns:
        value = row[column]
        if not column.endswith("_account_id") or value not in {None, ""}:
            return value
    elif not column.endswith("_account_id"):
        raise PlatformStateDataError.missing_column(table, column)

    platform_column = column.removesuffix("_account_id") + "_platform"
    platform = row[platform_column] if platform_column in source_columns else None
    if platform is None:
        return None
    if str(platform) != Platform.QQ_OFFICIAL.value:
        return ""
    account_id = str(qq_official_account_id or "").strip()
    if not account_id:
        raise PlatformStateDataError.missing_qq_official_account_id(f"{table}.{column}")
    return account_id


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(
            f"PRAGMA table_info({quote_sqlite_identifier(table)})"
        ).fetchall()
    }


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )
