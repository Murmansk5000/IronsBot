import sqlite3
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from ironsbot.shared.sqlite import (
    connect_sqlite,
    ensure_sqlite_column,
    ensure_sqlite_columns,
    open_sqlite,
    open_sqlite_schema,
    quote_sqlite_identifier,
    resolve_sqlite_path,
    sqlite_schema_statements,
    sqlite_table_columns,
)


def test_resolve_sqlite_path_uses_current_working_directory(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert resolve_sqlite_path("data/cache.sqlite") == tmp_path / "data/cache.sqlite"


def test_connect_sqlite_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "cache.sqlite"

    with connect_sqlite(path) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")

    assert path.exists()


def test_connect_sqlite_applies_default_pragmas(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite"

    with connect_sqlite(path) as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()
        synchronous = conn.execute("PRAGMA synchronous").fetchone()

    assert journal_mode is not None
    assert str(journal_mode[0]).lower() == "wal"
    assert synchronous is not None
    assert int(synchronous[0]) == 1


def test_open_sqlite_closes_connection(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite"

    with open_sqlite(path) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_sqlite_schema_statements_normalizes_single_statement() -> None:
    assert sqlite_schema_statements("CREATE TABLE sample (id INTEGER)") == (
        "CREATE TABLE sample (id INTEGER)",
    )


def test_open_sqlite_schema_initializes_schema(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite"

    with open_sqlite_schema(
        path,
        [
            "CREATE TABLE sample (id INTEGER PRIMARY KEY)",
            "CREATE INDEX idx_sample_id ON sample (id)",
        ],
    ) as conn:
        conn.execute("INSERT INTO sample (id) VALUES (1)")

    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT id FROM sample").fetchall()
        index_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()

    assert rows == [(1,)]
    assert ("idx_sample_id",) in index_rows


def test_ensure_sqlite_column_adds_missing_column_once(tmp_path: Path) -> None:
    with connect_sqlite(tmp_path / "cache.sqlite") as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")

        assert ensure_sqlite_column(
            conn,
            table_name="sample",
            column_name="name",
            column_definition="name TEXT NOT NULL DEFAULT ''",
        )
        assert not ensure_sqlite_column(
            conn,
            table_name="sample",
            column_name="name",
            column_definition="name TEXT NOT NULL DEFAULT ''",
        )

        assert sqlite_table_columns(conn, "sample") == {"id", "name"}


def test_ensure_sqlite_columns_adds_missing_columns_once(tmp_path: Path) -> None:
    with connect_sqlite(tmp_path / "cache.sqlite") as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")

        assert ensure_sqlite_columns(
            conn,
            table_name="sample",
            columns={
                "name": "name TEXT NOT NULL DEFAULT ''",
                "updated_at": "updated_at TEXT",
            },
        ) == {"name", "updated_at"}
        assert ensure_sqlite_columns(
            conn,
            table_name="sample",
            columns={
                "name": "name TEXT NOT NULL DEFAULT ''",
                "updated_at": "updated_at TEXT",
            },
        ) == set()

        assert sqlite_table_columns(conn, "sample") == {
            "id",
            "name",
            "updated_at",
        }


def test_quote_sqlite_identifier_rejects_unsafe_names() -> None:
    assert quote_sqlite_identifier("safe_name_1") == '"safe_name_1"'

    with pytest.raises(ValueError):
        quote_sqlite_identifier("sample; DROP TABLE sample")
