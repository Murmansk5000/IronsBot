import sqlite3
from pathlib import Path

from sqlalchemy import text

from ironsbot.integrations.db_registry import DatabaseManager

EXPECTED_VALUE = 7


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
