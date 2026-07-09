import sqlite3
from pathlib import Path

from ironsbot.services.bilibili.preferences import (
    BiliPushPreferenceStore,
    bili_push_subscription_key,
    normalize_push_mode_text,
)


def test_bili_push_preference_store_sets_gets_and_clears_mode(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "bili_preferences.sqlite"
    store = BiliPushPreferenceStore(db_path)

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


def test_bili_push_subscription_key_and_mode_normalization() -> None:
    assert bili_push_subscription_key(123456) == "bili_push:123456"
    assert normalize_push_mode_text(" content ") == "full"
    assert normalize_push_mode_text("url") == "link"
    assert normalize_push_mode_text("default") is None
