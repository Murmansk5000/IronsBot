import asyncio
from pathlib import Path
from typing import Any

from ironsbot.services.bilibili.monitor import _push_new_dynamics
from ironsbot.services.bilibili.parser import dynamic_content
from ironsbot.services.bilibili.push import (
    build_dynamic_history_snapshot_for_item,
    mark_history_snapshot_pushed,
)
from ironsbot.services.bilibili.service import BiliFeedResponse
from tests.helpers.bilibili import build_test_bilibili_service

AUTHOR_UID = 59224295
SEER_UID = 1310714247
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
        _categories: object,
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


def test_monitor_marks_category_muted_seer_dynamic_as_processed(
    tmp_path: Path,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    item = _item()
    item["id_str"] = "seer-lottery"
    item["modules"]["module_author"]["mid"] = SEER_UID
    item["modules"]["module_dynamic"]["major"]["opus"]["summary"]["text"] = (
        "恭喜玩家中奖，请及时查看私信通知。"
    )
    sent: list[str] = []

    async def send_push(
        _item: dict[str, Any],
        _pub_ts: int,
        _author_mid: int,
        _targets: object,
        _categories: object,
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

    saved = service.history.get("seer-lottery")
    assert sent == []
    assert changed
    assert checkpoints == {SEER_UID: PUB_TS}
    assert saved is not None
    assert saved.pushed
    assert not saved.suppressed


def test_monitor_enriches_empty_seer_dynamic_before_saving(
    tmp_path: Path,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    item = _item()
    item["id_str"] = "seer-opus-detail"
    item["modules"]["module_author"]["mid"] = SEER_UID
    item["modules"]["module_dynamic"] = {
        "major": {"draw": {"items": [{"src": "https://example.test/a.png"}]}}
    }
    detail = _item()
    detail["id_str"] = "seer-opus-detail"
    detail["modules"]["module_author"]["mid"] = SEER_UID
    detail["modules"]["module_dynamic"]["major"] = {
        "opus": {"summary": {"text": "巅峰之战年度总决赛即将开幕"}}
    }

    async def fetch_detail(_cookie: str, _dynamic_id: str) -> BiliFeedResponse:
        return BiliFeedResponse(200, {"code": 0, "data": {"item": detail}})

    async def send_push(
        _item: dict[str, Any],
        _pub_ts: int,
        _author_mid: int,
        _targets: object,
        _categories: object,
    ) -> None:
        return None

    service.fetch_detail = fetch_detail
    asyncio.run(
        _push_new_dynamics(
            service,
            [(PUB_TS, item)],
            {},
            send_push,
            cookie="test-cookie",
        )
    )

    saved = service.history.get("seer-opus-detail")
    assert saved is not None
    assert dynamic_content(saved.item) == "巅峰之战年度总决赛即将开幕"
