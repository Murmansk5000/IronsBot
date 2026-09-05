import sqlite3
from pathlib import Path

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
            value = session.connection().exec_driver_sql(
                "SELECT value FROM sample"
            ).scalar_one()
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
        value = session.connection().exec_driver_sql(
            "SELECT value FROM sample"
        ).scalar_one()
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
        value = session.connection().exec_driver_sql(
            "SELECT value FROM sample"
        ).scalar_one()
    assert value == "active"
