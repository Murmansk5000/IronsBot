import sqlite3
from pathlib import Path

import pytest

from ironsbot.integrations.storage.sqlite_handoff import SqliteHandoff


def test_backup_restores_old_schema_before_old_code_restarts(tmp_path: Path) -> None:
    target = tmp_path / "samples.sqlite"
    with sqlite3.connect(target) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE old(id INTEGER)")
        conn.execute("INSERT INTO old VALUES(1)")
    handoff = SqliteHandoff.within(tmp_path, "samples.sqlite")
    handoff.save()
    with sqlite3.connect(target) as conn:
        conn.execute("DROP TABLE old")
        conn.execute("CREATE TABLE upgraded(id INTEGER)")
    handoff.restore()
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT * FROM old").fetchall() == [(1,)]
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    handoff.finish()
    assert not handoff.snapshot.exists()


@pytest.mark.parametrize("path", ["../escape.sqlite", "/outside.sqlite", "."])
def test_handoff_rejects_paths_outside_data(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError):
        SqliteHandoff.within(tmp_path, path)
