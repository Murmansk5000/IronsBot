import sqlite3
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    SqliteMigrationError,
    ensure_sqlite_columns,
    quote_sqlite_identifier,
    resolve_sqlite_path,
    sqlite_table_columns,
)


class _MigrationError(RuntimeError):
    pass


def test_resolve_sqlite_path_uses_current_working_directory(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert resolve_sqlite_path("data/cache.sqlite") == tmp_path / "data/cache.sqlite"


def test_database_creates_parent_and_applies_pragmas(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "cache.sqlite"

    with SqliteDatabase(path).connect() as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        synchronous = connection.execute("PRAGMA synchronous").fetchone()
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()

    assert path.exists()
    assert journal_mode is not None
    assert str(journal_mode[0]).lower() == "wal"
    assert synchronous is not None
    assert int(synchronous[0]) == 1
    assert busy_timeout == (5000,)


def test_database_closes_connection(tmp_path: Path) -> None:
    with SqliteDatabase(tmp_path / "cache.sqlite").connect() as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_database_applies_migrations_once(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite"
    callback_runs: list[int] = []

    def record_migration(connection: sqlite3.Connection) -> None:
        callback_runs.append(1)
        connection.execute("INSERT INTO sample (id) VALUES (1)")

    database = SqliteDatabase(
        path,
        migrations=(
            SqliteMigration(
                1,
                ("CREATE TABLE sample (id INTEGER PRIMARY KEY)",),
                record_migration,
            ),
        ),
    )

    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
    with database.connect() as connection:
        assert connection.execute("SELECT id FROM sample").fetchall() == [(1,)]

    assert callback_runs == [1]


def test_namespaced_migrations_share_one_database(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    first = SqliteDatabase(
        path,
        migrations=(
            SqliteMigration(1, ("CREATE TABLE first_state (id INTEGER)",)),
        ),
        migration_namespace="first_state",
    )
    second = SqliteDatabase(
        path,
        migrations=(
            SqliteMigration(1, ("CREATE TABLE second_state (id INTEGER)",)),
        ),
        migration_namespace="second_state",
    )

    with first.connect():
        pass
    with second.connect() as connection:
        versions = connection.execute(
            "SELECT namespace, version FROM ironsbot_schema_migrations "
            "ORDER BY namespace"
        ).fetchall()
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert versions == [("first_state", 1), ("second_state", 1)]
    assert {"first_state", "second_state"}.issubset(tables)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)


def test_namespaced_migration_rejects_only_newer_matching_namespace(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE ironsbot_schema_migrations ("
            "namespace TEXT PRIMARY KEY, version INTEGER NOT NULL, "
            "updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO ironsbot_schema_migrations VALUES ('first', 2, '')"
        )
        connection.execute(
            "INSERT INTO ironsbot_schema_migrations VALUES ('second', 1, '')"
        )

    first = SqliteDatabase(
        path,
        migrations=(SqliteMigration(1, ("CREATE TABLE first (id INTEGER)",)),),
        migration_namespace="first",
    )
    second = SqliteDatabase(
        path,
        migrations=(SqliteMigration(1, ("CREATE TABLE second (id INTEGER)",)),),
        migration_namespace="second",
    )

    with pytest.raises(SqliteMigrationError, match="2 > 1"), first.connect():
        pass
    with second.connect():
        pass


def test_unversioned_database_is_migrated_without_losing_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cache.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO sample (id) VALUES (7)")

    def add_columns(connection: sqlite3.Connection) -> None:
        ensure_sqlite_columns(
            connection,
            table_name="sample",
            columns={"name": "name TEXT NOT NULL DEFAULT ''"},
        )

    database = SqliteDatabase(
        path,
        migrations=(SqliteMigration(1, callback=add_columns),),
    )
    with database.connect() as connection:
        assert connection.execute(
            "SELECT id, name FROM sample"
        ).fetchall() == [(7, "")]
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)


def test_pending_migrations_are_atomic(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite"

    def fail(_connection: sqlite3.Connection) -> None:
        raise _MigrationError

    database = SqliteDatabase(
        path,
        migrations=(
            SqliteMigration(
                1,
                ("CREATE TABLE sample (id INTEGER PRIMARY KEY)",),
            ),
            SqliteMigration(2, callback=fail),
        ),
    )

    with pytest.raises(_MigrationError), database.connect():
        pass

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall() == []


def test_newer_database_version_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 2")

    database = SqliteDatabase(
        path,
        migrations=(
            SqliteMigration(1, ("CREATE TABLE sample (id INTEGER)",)),
        ),
    )

    with pytest.raises(SqliteMigrationError, match="2 > 1"), database.connect():
        pass


def test_migration_versions_must_be_contiguous(tmp_path: Path) -> None:
    with pytest.raises(SqliteMigrationError, match="contiguous"):
        SqliteDatabase(
            tmp_path / "cache.sqlite",
            migrations=(
                SqliteMigration(2, ("CREATE TABLE sample (id INTEGER)",)),
            ),
        )


def test_ensure_sqlite_columns_adds_missing_columns_once(tmp_path: Path) -> None:
    with SqliteDatabase(tmp_path / "cache.sqlite").connect() as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")

        assert ensure_sqlite_columns(
            connection,
            table_name="sample",
            columns={
                "name": "name TEXT NOT NULL DEFAULT ''",
                "updated_at": "updated_at TEXT",
            },
        ) == {"name", "updated_at"}
        assert (
            ensure_sqlite_columns(
                connection,
                table_name="sample",
                columns={
                    "name": "name TEXT NOT NULL DEFAULT ''",
                    "updated_at": "updated_at TEXT",
                },
            )
            == set()
        )
        assert sqlite_table_columns(connection, "sample") == {
            "id",
            "name",
            "updated_at",
        }


def test_quote_sqlite_identifier_rejects_unsafe_names() -> None:
    assert quote_sqlite_identifier("safe_name_1") == '"safe_name_1"'

    with pytest.raises(ValueError):
        quote_sqlite_identifier("sample; DROP TABLE sample")
