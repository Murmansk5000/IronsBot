# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

RowFactory = Callable[[sqlite3.Cursor, Sequence[Any]], object]
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
    if column_name in sqlite_table_columns(conn, table_name):
        return False

    table_sql = quote_sqlite_identifier(table_name)
    conn.execute(f"ALTER TABLE {table_sql} ADD COLUMN {column_definition}")
    return True


__all__ = [
    "connect_sqlite",
    "ensure_sqlite_column",
    "open_sqlite",
    "quote_sqlite_identifier",
    "resolve_sqlite_path",
    "sqlite_table_columns",
]
