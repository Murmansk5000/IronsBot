import sqlite3
from pathlib import Path

from ironsbot.integrations.storage.bilibili_preferences import (
    SqliteBiliPushPreferenceStore,
)
from ironsbot.services.bilibili.preferences import (
    bili_push_subscription_key,
    normalize_push_mode_text,
)

PREFERENCE_SCHEMA_VERSION = 2


def test_bili_push_preference_store_sets_gets_and_clears_mode(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "bili_preferences.sqlite"
    store = SqliteBiliPushPreferenceStore(db_path)

    assert store.get_mode("group", 1001, 123456) is None

    store.set_mode("group", 1001, 123456, "full")

    assert store.get_mode("group", 1001, 123456) == "full"

    with sqlite3.connect(db_path) as conn:
        indexes = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
    assert "idx_bili_push_preferences_uid" in indexes

    store.clear_mode("group", 1001, 123456)

    assert store.get_mode("group", 1001, 123456) is None


def test_bili_push_preference_migration_preserves_runtime_mode_overrides(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "bili_preferences.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version = 1")
        conn.execute(
            "CREATE TABLE bili_push_preferences ("
            "target_type TEXT NOT NULL, target_id INTEGER NOT NULL, "
            "uid INTEGER NOT NULL, mode TEXT NOT NULL, updated_at TEXT NOT NULL, "
            "PRIMARY KEY (target_type, target_id, uid)"
            ")"
        )
        conn.execute(
            "INSERT INTO bili_push_preferences VALUES (?, ?, ?, ?, ?)",
            ("group", 1001, 123456, "link", "2026-08-01T00:00:00+00:00"),
        )

    store = SqliteBiliPushPreferenceStore(db_path)

    assert store.get_mode("group", 1001, 123456) == "link"
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute("PRAGMA user_version").fetchone()[0]
            == PREFERENCE_SCHEMA_VERSION
        )


def test_bili_push_subscription_key_and_mode_normalization() -> None:
    assert bili_push_subscription_key(123456) == "bili_push:123456"
    assert normalize_push_mode_text(" content ") == "full"
    assert normalize_push_mode_text("url") == "link"
    assert normalize_push_mode_text("default") is None
