import asyncio
from pathlib import Path
from typing import Any

from ironsbot.services.bilibili.monitor import _push_new_dynamics
from ironsbot.services.bilibili.push import (
    build_dynamic_history_snapshot_for_item,
    mark_history_snapshot_pushed,
)
from tests.helpers.bilibili import build_test_bilibili_service

AUTHOR_UID = 59224295
PUB_TS = 1_786_043_659


def _item() -> dict[str, Any]:
    return {
        "id_str": "1233666043677769736",
        "modules": {
            "module_author": {
                "mid": AUTHOR_UID,
                "name": "蝶夏Channel",
                "pub_ts": PUB_TS,
            },
            "module_dynamic": {
                "major": {"opus": {"summary": {"text": "一条测试动态"}}}
            },
        },
    }


def test_monitor_does_not_redeliver_persisted_dynamic_when_checkpoint_is_missing(
    tmp_path: Path,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    item = _item()
    snapshot = build_dynamic_history_snapshot_for_item(
        item,
        pub_ts=PUB_TS,
        suppress_patterns=[],
    )
    assert snapshot is not None
    service.history.save_snapshot(mark_history_snapshot_pushed(snapshot))

    sent: list[str] = []

    async def send_push(
        _item: dict[str, Any],
        _pub_ts: int,
        _author_mid: int,
        _targets: object,
    ) -> None:
        sent.append("sent")

    checkpoints: dict[int, int] = {}
    changed = asyncio.run(
        _push_new_dynamics(
            service,
            [(PUB_TS, item)],
            checkpoints,
            send_push,
        )
    )

    assert sent == []
    assert changed
    assert checkpoints == {AUTHOR_UID: PUB_TS}
