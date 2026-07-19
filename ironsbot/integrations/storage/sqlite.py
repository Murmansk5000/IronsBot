# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

RowFactory = Callable[[sqlite3.Cursor, sqlite3.Row], object] | type[sqlite3.Row]
MigrationCallback = Callable[[sqlite3.Connection], None]
_SQLITE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SqliteMigrationError(RuntimeError):
    @classmethod
    def invalid_plan(cls, versions: Sequence[int]) -> SqliteMigrationError:
        return cls(f"SQLite migration versions must be contiguous: {list(versions)}")

    @classmethod
    def newer_database(
        cls,
        *,
        current_version: int,
        target_version: int,
    ) -> SqliteMigrationError:
        return cls(
            "SQLite database schema is newer than this application: "
            f"{current_version} > {target_version}"
        )


@dataclass(frozen=True, slots=True)
class SqliteMigration:
    version: int
    statements: tuple[str, ...] = ()
    callback: MigrationCallback | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError(self.version)
        if not self.statements and self.callback is None:
            raise ValueError(self.version)


@dataclass(frozen=True, slots=True)
class SqliteDatabase:
    path: str | Path
    migrations: tuple[SqliteMigration, ...] = ()
    row_factory: RowFactory | None = None
    pragmas: bool = True

    def __post_init__(self) -> None:
        versions = tuple(migration.version for migration in self.migrations)
        if versions != tuple(range(1, len(versions) + 1)):
            raise SqliteMigrationError.invalid_plan(versions)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        resolved = resolve_sqlite_path(self.path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(resolved)
        try:
            if self.pragmas:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=NORMAL")
            if self.row_factory is not None:
                connection.row_factory = self.row_factory
            self._apply_migrations(connection)
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()
        finally:
            connection.close()

    def _apply_migrations(self, connection: sqlite3.Connection) -> None:
        if not self.migrations:
            return

        target_version = self.migrations[-1].version
        connection.execute("BEGIN IMMEDIATE")
        try:
            current_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            _validate_database_version(
                current_version=current_version,
                target_version=target_version,
            )

            for migration in self.migrations[current_version:]:
                for statement in migration.statements:
                    connection.execute(statement)
                if migration.callback is not None:
                    migration.callback(connection)
                connection.execute(f"PRAGMA user_version = {migration.version}")
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()


def _validate_database_version(
    *,
    current_version: int,
    target_version: int,
) -> None:
    if current_version > target_version:
        raise SqliteMigrationError.newer_database(
            current_version=current_version,
            target_version=target_version,
        )


def quote_sqlite_identifier(identifier: str) -> str:
    if not _SQLITE_IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(identifier)
    return f'"{identifier}"'


def resolve_sqlite_path(path: str | Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved


def sqlite_table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    table_sql = quote_sqlite_identifier(table_name)
    return {
        str(row[1])
        for row in connection.execute(
            f"PRAGMA table_info({table_sql})"
        ).fetchall()
    }


def ensure_sqlite_columns(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    columns: Mapping[str, str],
) -> set[str]:
    table_sql = quote_sqlite_identifier(table_name)
    existing = sqlite_table_columns(connection, table_name)
    added: set[str] = set()

    for column_name, column_definition in columns.items():
        quote_sqlite_identifier(column_name)
        if column_name in existing:
            continue
        connection.execute(
            f"ALTER TABLE {table_sql} ADD COLUMN {column_definition}"
        )
        existing.add(column_name)
        added.add(column_name)

    return added
