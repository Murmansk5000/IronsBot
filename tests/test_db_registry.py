import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ironsbot.integrations.db_registry import DatabaseManager

EXPECTED_VALUE = 7


class InvalidStagedDatabaseError(ValueError):
    pass


def test_database_manager_loads_sqlite_file_into_memory(tmp_path: Path) -> None:
    source_path = tmp_path / "source.sqlite"
    with sqlite3.connect(source_path) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute("INSERT INTO sample (id, name) VALUES (1, 'alpha')")

    manager = DatabaseManager()
    manager.load_from_file("unit", str(source_path))

    engine = manager.get_engine("unit")
    assert engine is not None
    with manager.session("unit") as session:
        assert session is not None
        row = (
            session.connection()
            .execute(text("SELECT name FROM sample WHERE id = 1"))
            .scalar_one()
        )
    manager.close()

    assert row == "alpha"


@pytest.mark.parametrize("operation", ["load", "register", "close"])
def test_old_engine_lives_until_last_snapshot_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    path = tmp_path / "source.sqlite"
    with sqlite3.connect(path) as source:
        source.execute("CREATE TABLE sample (value TEXT)")
        source.execute("INSERT INTO sample VALUES ('old')")
    manager = DatabaseManager()
    manager.load_from_file("unit", str(path))
    old = manager.get_engine("unit")
    assert old is not None
    dispose = Mock(wraps=old.dispose)
    monkeypatch.setattr(old, "dispose", dispose)
    with manager.snapshot(("unit", "missing", "unit")) as snapshot:
        assert set(snapshot) == {"unit"}
        with manager.all_sessions() as sessions:
            assert (
                sessions["unit"]
                .connection()
                .exec_driver_sql("SELECT value FROM sample")
                .scalar_one()
                == "old"
            )
            if operation == "load":
                with sqlite3.connect(path) as source:
                    source.execute("UPDATE sample SET value='new'")
                manager.load_from_file("unit", str(path))
                with manager.session("unit") as fresh:
                    assert fresh is not None
                    assert (
                        fresh.connection()
                        .exec_driver_sql("SELECT value FROM sample")
                        .scalar_one()
                        == "new"
                    )
            elif operation == "register":
                manager.register("unit")
            else:
                manager.close()
            assert manager.get_engine("unit") is not old
            assert (
                sessions["unit"]
                .connection()
                .exec_driver_sql("SELECT value FROM sample")
                .scalar_one()
                == "old"
            )
            dispose.assert_not_called()
        dispose.assert_not_called()
        with snapshot["unit"].connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT value FROM sample").scalar_one()
                == "old"
            )
    dispose.assert_called_once_with()
    manager.close()
    dispose.assert_called_once_with()


def test_snapshot_exception_releases_retired_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = DatabaseManager()
    manager.register("unit")
    engine = manager.get_engine("unit")
    assert engine is not None
    dispose = Mock(wraps=engine.dispose)
    monkeypatch.setattr(engine, "dispose", dispose)
    with pytest.raises(RuntimeError), manager.snapshot():
        manager.close()
        raise RuntimeError
    dispose.assert_called_once_with()


def test_session_retains_old_data_during_threaded_publication(tmp_path: Path) -> None:
    path = tmp_path / "source.sqlite"
    with sqlite3.connect(path) as source:
        source.execute("CREATE TABLE sample (value TEXT)")
        source.execute("INSERT INTO sample VALUES ('old')")
    manager = DatabaseManager()
    manager.load_from_file("unit", str(path))
    try:
        # Join after the session exits even if publication times out, so a lock
        # regression fails the assertion rather than deadlocking test teardown.
        with (
            ThreadPoolExecutor(max_workers=1) as executor,
            manager.session("unit") as old,
        ):
            assert old is not None
            connection = old.connection()
            assert (
                connection.exec_driver_sql("SELECT value FROM sample").scalar_one()
                == "old"
            )
            with sqlite3.connect(path) as source:
                source.execute("UPDATE sample SET value='new'")
            publication = executor.submit(manager.load_from_file, "unit", str(path))
            publication.result(timeout=5)
            assert (
                connection.exec_driver_sql("SELECT value FROM sample").scalar_one()
                == "old"
            )
            with manager.session("unit") as fresh:
                assert fresh is not None
                assert (
                    fresh.connection()
                    .exec_driver_sql("SELECT value FROM sample")
                    .scalar_one()
                    == "new"
                )
    finally:
        manager.close()


def test_database_manager_notifies_listener_after_atomic_load(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.sqlite"
    with sqlite3.connect(source_path) as conn:
        conn.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        conn.execute("INSERT INTO sample VALUES ('loaded')")

    manager = DatabaseManager()
    observed: list[str] = []

    def on_loaded() -> None:
        with manager.session("unit") as session:
            assert session is not None
            value = (
                session.connection()
                .exec_driver_sql("SELECT value FROM sample")
                .scalar_one()
            )
        observed.append(str(value))

    manager.add_load_listener("unit", on_loaded)
    manager.load_from_file("unit", str(source_path))

    assert observed == ["loaded"]


def test_database_manager_listener_failure_does_not_reject_database(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.sqlite"
    with sqlite3.connect(source_path) as conn:
        conn.execute("CREATE TABLE sample (value INTEGER NOT NULL)")
        conn.execute("INSERT INTO sample VALUES (?)", (EXPECTED_VALUE,))

    manager = DatabaseManager()

    def fail() -> None:
        raise RuntimeError

    manager.add_load_listener("unit", fail)
    manager.load_from_file("unit", str(source_path))

    with manager.session("unit") as session:
        assert session is not None
        value = (
            session.connection()
            .exec_driver_sql("SELECT value FROM sample")
            .scalar_one()
        )
    assert value == EXPECTED_VALUE


def test_database_manager_rejects_invalid_staged_database_without_replacing_active(
    tmp_path: Path,
) -> None:
    valid_source = tmp_path / "valid.sqlite"
    invalid_source = tmp_path / "invalid.sqlite"
    for source, value in ((valid_source, "active"), (invalid_source, "invalid")):
        with sqlite3.connect(source) as conn:
            conn.execute("CREATE TABLE sample (value TEXT NOT NULL)")
            conn.execute("INSERT INTO sample VALUES (?)", (value,))

    manager = DatabaseManager()

    def require_active_value(engine: Engine) -> None:
        with engine.connect() as connection:
            value = connection.execute(text("SELECT value FROM sample")).scalar_one()
        if value != "active":
            raise InvalidStagedDatabaseError

    manager.add_load_validator("unit", require_active_value)
    manager.load_from_file("unit", str(valid_source))

    with pytest.raises(InvalidStagedDatabaseError):
        manager.load_from_file("unit", str(invalid_source))

    with manager.session("unit") as session:
        assert session is not None
        value = (
            session.connection()
            .exec_driver_sql("SELECT value FROM sample")
            .scalar_one()
        )
    assert value == "active"


@pytest.mark.parametrize("failure", ["missing", "corrupt", "validator"])
def test_failed_staging_preserves_active_database_and_disposes_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    valid = tmp_path / "valid.sqlite"
    with sqlite3.connect(valid) as source:
        source.execute("CREATE TABLE sample (value TEXT)")
        source.execute("INSERT INTO sample VALUES ('active')")
    manager = DatabaseManager()
    manager.load_from_file("unit", str(valid))
    active = manager.get_engine("unit")
    staged = manager._create_memory_engine()
    dispose = Mock(wraps=staged.dispose)
    monkeypatch.setattr(staged, "dispose", dispose)
    monkeypatch.setattr(manager, "_create_memory_engine", lambda: staged)
    notified = Mock()
    manager.add_load_listener("unit", notified)
    candidate = tmp_path / "absent-parent" / "missing.sqlite"
    if failure == "corrupt":
        candidate = tmp_path / "corrupt.sqlite"
        candidate.write_bytes(b"not a sqlite database")
    elif failure == "validator":
        candidate = valid

        def reject(_engine: Engine) -> None:
            raise InvalidStagedDatabaseError

        manager.add_load_validator("unit", reject)
    with pytest.raises((sqlite3.DatabaseError, InvalidStagedDatabaseError)):
        manager.load_from_file("unit", str(candidate))
    dispose.assert_called_once_with()
    notified.assert_not_called()
    assert manager.get_engine("unit") is active
    with manager.session("unit") as session:
        assert session is not None
        assert (
            session.connection()
            .exec_driver_sql("SELECT value FROM sample")
            .scalar_one()
            == "active"
        )
    if failure == "missing":
        assert not candidate.parent.exists()
    manager.close()
