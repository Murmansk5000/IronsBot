# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

RowFactory = Callable[[sqlite3.Cursor, sqlite3.Row], object] | type[sqlite3.Row]
SqliteSchema = str | Sequence[str]
_SQLITE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_sqlite_identifier(identifier: str) -> str:
    if not _SQLITE_IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(identifier)
    return f'"{identifier}"'


def resolve_sqlite_path(path: str | Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved


def connect_sqlite(
    path: str | Path,
    *,
    row_factory: RowFactory | None = None,
    pragmas: bool = True,
) -> sqlite3.Connection:
    resolved = resolve_sqlite_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    if pragmas:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    if row_factory is not None:
        conn.row_factory = row_factory
    return conn


@contextmanager
def open_sqlite(
    path: str | Path,
    *,
    row_factory: RowFactory | None = None,
    pragmas: bool = True,
) -> Iterator[sqlite3.Connection]:
    conn = connect_sqlite(path, row_factory=row_factory, pragmas=pragmas)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def sqlite_schema_statements(schema: SqliteSchema) -> tuple[str, ...]:
    if isinstance(schema, str):
        return (schema,)
    return tuple(schema)


@contextmanager
def open_sqlite_schema(
    path: str | Path,
    schema: SqliteSchema,
    *,
    row_factory: RowFactory | None = None,
    pragmas: bool = True,
) -> Iterator[sqlite3.Connection]:
    with open_sqlite(path, row_factory=row_factory, pragmas=pragmas) as conn:
        for statement in sqlite_schema_statements(schema):
            conn.execute(statement)
        yield conn


def sqlite_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    table_sql = quote_sqlite_identifier(table_name)
    return {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({table_sql})").fetchall()
    }


def ensure_sqlite_column(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> bool:
    return column_name in ensure_sqlite_columns(
        conn,
        table_name=table_name,
        columns={column_name: column_definition},
    )


def ensure_sqlite_columns(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    columns: Mapping[str, str],
) -> set[str]:
    table_sql = quote_sqlite_identifier(table_name)
    existing = sqlite_table_columns(conn, table_name)
    added: set[str] = set()

    for column_name, column_definition in columns.items():
        quote_sqlite_identifier(column_name)
        if column_name in existing:
            continue
        conn.execute(f"ALTER TABLE {table_sql} ADD COLUMN {column_definition}")
        existing.add(column_name)
        added.add(column_name)

    return added


__all__ = [
    "connect_sqlite",
    "ensure_sqlite_column",
    "ensure_sqlite_columns",
    "open_sqlite",
    "open_sqlite_schema",
    "quote_sqlite_identifier",
    "resolve_sqlite_path",
    "sqlite_schema_statements",
    "sqlite_table_columns",
]
