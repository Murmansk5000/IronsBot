import sqlite3
from pathlib import Path
from typing import Any

from ironsbot.integrations.storage.bilibili_history import (
    SqliteBiliDynamicHistoryStore,
)
from ironsbot.services.bilibili.dynamic_history import save_target_dynamics
from ironsbot.services.bilibili.push import DynamicHistorySnapshot

AUTHOR_UID = 1310714247
PUB_TS = 1781004683


def _dynamic_item(
    *,
    text: str = "恭喜测试用户获得一个闪亮奖励内容",
) -> dict[str, Any]:
    return {
        "id_str": "dynamic-1",
        "modules": {
            "module_author": {
                "mid": AUTHOR_UID,
                "name": "Seer",
                "pub_ts": PUB_TS,
            },
            "module_dynamic": {
                "major": {
                    "opus": {
                        "summary": {"text": text},
                    }
                }
            },
        },
    }


def test_save_dynamic_history_snapshot_persists_fields(tmp_path: Path) -> None:
    history = SqliteBiliDynamicHistoryStore(tmp_path / "history.sqlite", 10)
    item = {"id_str": "dynamic-1"}
    snapshot = DynamicHistorySnapshot(
        item=item,
        pub_ts=PUB_TS,
        author_mid=AUTHOR_UID,
        author_name="Seer",
        brief="test dynamic",
        pushed=True,
        suppressed=True,
        suppression_reason="test rule",
    )

    history.save_snapshot(snapshot)

    saved = history.get("dynamic-1")
    assert saved is not None
    assert saved.item == item
    assert saved.pub_ts == PUB_TS
    assert saved.uid == AUTHOR_UID
    assert saved.pushed
    assert saved.suppressed
    assert saved.suppression_reason == "test rule"
    assert saved.summary == ""
    assert not saved.summary_generated_by_ai


def test_dynamic_history_preserves_saved_summary_on_snapshot_refresh(
    tmp_path: Path,
) -> None:
    history = SqliteBiliDynamicHistoryStore(tmp_path / "history.sqlite", 10)
    snapshot = DynamicHistorySnapshot(
        item=_dynamic_item(text="完整原文"),
        pub_ts=PUB_TS,
        author_mid=AUTHOR_UID,
        author_name="Seer",
        brief="test dynamic",
    )
    history.save_snapshot(snapshot)
    history.save_summary("dynamic-1", "持久化摘要", generated_by_ai=True)
    history.save_snapshot(snapshot)

    saved = history.get("dynamic-1")
    assert saved is not None
    assert saved.summary == "持久化摘要"
    assert saved.summary_generated_by_ai


def test_dynamic_history_upgrades_version_two_database(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE dynamics (
                dynamic_id TEXT PRIMARY KEY,
                uid INTEGER NOT NULL,
                author_name TEXT NOT NULL,
                pub_ts INTEGER NOT NULL,
                brief TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                pushed INTEGER NOT NULL DEFAULT 0,
                suppressed INTEGER NOT NULL DEFAULT 0,
                suppression_reason TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                delivery_claimed_at REAL NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            INSERT INTO dynamics (
                dynamic_id, uid, author_name, pub_ts, brief, raw_json,
                created_at, updated_at
            ) VALUES ('old', 1, 'Seer', 2, '旧动态', '{}', 3, 3)
            """
        )
        connection.execute("PRAGMA user_version = 2")

    history = SqliteBiliDynamicHistoryStore(path, 10)
    record = history.get("old")

    assert record is not None
    assert record.summary == ""
    assert not record.summary_generated_by_ai
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (3,)


def test_save_target_dynamic_history_builds_and_saves_snapshots(
    tmp_path: Path,
) -> None:
    history = SqliteBiliDynamicHistoryStore(tmp_path / "history.sqlite", 10)
    pattern = "恭喜.*奖励"

    saved_count = save_target_dynamics(
        history,
        [
            (PUB_TS, _dynamic_item()),
            (PUB_TS, {"id_str": "missing-author"}),
        ],
        suppress_patterns=[pattern],
    )

    assert saved_count == 1
    records = history.list()
    assert len(records) == 1
    assert records[0].uid == AUTHOR_UID
    assert records[0].suppressed
    assert records[0].suppression_reason.endswith(pattern)


def test_dynamic_delivery_claim_is_shared_between_history_store_instances(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.sqlite"
    first = SqliteBiliDynamicHistoryStore(path, 10)
    second = SqliteBiliDynamicHistoryStore(path, 10)
    first.save_snapshot(
        DynamicHistorySnapshot(
            item={"id_str": "dynamic-1"},
            pub_ts=PUB_TS,
            author_mid=AUTHOR_UID,
            author_name="Seer",
            brief="test dynamic",
        )
    )

    assert first.try_claim_delivery("dynamic-1")
    assert not second.try_claim_delivery("dynamic-1")

    first.release_delivery_claim("dynamic-1")

    assert second.try_claim_delivery("dynamic-1")
