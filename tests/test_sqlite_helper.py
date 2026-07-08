import sqlite3
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from ironsbot.shared.sqlite import (
    connect_sqlite,
    ensure_sqlite_column,
    open_sqlite,
    quote_sqlite_identifier,
    resolve_sqlite_path,
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


def test_quote_sqlite_identifier_rejects_unsafe_names() -> None:
    assert quote_sqlite_identifier("safe_name_1") == '"safe_name_1"'

    with pytest.raises(ValueError):
        quote_sqlite_identifier("sample; DROP TABLE sample")
