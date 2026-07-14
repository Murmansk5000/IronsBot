import sqlite3
from pathlib import Path

from sqlalchemy import text

from ironsbot.integrations.db_registry import DatabaseManager


def test_database_manager_loads_sqlite_file_into_memory(tmp_path: Path) -> None:
    source_path = tmp_path / "source.sqlite"
    with sqlite3.connect(source_path) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute("INSERT INTO sample (id, name) VALUES (1, 'alpha')")

    manager = DatabaseManager()
    hook_calls: list[str] = []
    manager.register_post_load_hook("unit", lambda _engine: hook_calls.append("unit"))
    manager.load_from_file("unit", str(source_path))

    session_gen = manager.get_session("unit")
    assert session_gen is not None
    try:
        session = next(session_gen)
        row = session.connection().execute(
            text("SELECT name FROM sample WHERE id = 1")
        ).scalar_one()
    finally:
        session_gen.close()
        manager.dispose_all()

    assert row == "alpha"
    assert hook_calls == ["unit"]
