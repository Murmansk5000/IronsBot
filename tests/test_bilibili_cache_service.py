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
