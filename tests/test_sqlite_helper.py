from pathlib import Path

from pytest import MonkeyPatch

from ironsbot.shared.sqlite import connect_sqlite, resolve_sqlite_path


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
