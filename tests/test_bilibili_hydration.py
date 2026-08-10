import asyncio
import time
from pathlib import Path
from typing import Any

from ironsbot.services.bilibili.hydration import hydrate_dynamic_item
from ironsbot.services.bilibili.parser import dynamic_content
from ironsbot.services.bilibili.push import build_dynamic_history_snapshot
from ironsbot.services.bilibili.service import BiliFeedResponse
from tests.helpers.bilibili import build_test_bilibili_service

SEER_UID = 1310714247


def _item(*, body: str = "", item_id: str = "123456") -> dict[str, Any]:
    major: dict[str, Any]
    if body:
        major = {"opus": {"summary": {"text": body}, "pics": []}}
    else:
        major = {"draw": {"items": [{"src": "https://example.test/image.png"}]}}
    return {
        "id_str": item_id,
        "modules": {
            "module_author": {
                "mid": SEER_UID,
                "name": "赛尔号",
                "pub_ts": int(time.time()),
            },
            "module_dynamic": {
                "major": major,
                "topic": {"name": "赛尔号巅峰之战"},
            },
        },
    }


def _detail_response(item: dict[str, Any]) -> BiliFeedResponse:
    return BiliFeedResponse(status_code=200, data={"code": 0, "data": {"item": item}})


def test_hydrate_dynamic_item_uses_opus_detail_for_old_draw_structure() -> None:
    source = _item()
    detail = _item(body="赛尔号大师赛年度总决赛即将开幕！")

    async def fetch_detail(_cookie: str, _dynamic_id: str) -> BiliFeedResponse:
        return _detail_response(detail)

    hydrated = asyncio.run(
        hydrate_dynamic_item(
            source,
            cookie="test-cookie",
            fetch_detail=fetch_detail,
        )
    )

    assert dynamic_content(hydrated) == "赛尔号大师赛年度总决赛即将开幕！"


def test_hydrate_dynamic_item_keeps_original_when_detail_is_invalid() -> None:
    source = _item()
    mismatched = _item(body="不应采用", item_id="different")

    async def fetch_detail(_cookie: str, _dynamic_id: str) -> BiliFeedResponse:
        return _detail_response(mismatched)

    hydrated = asyncio.run(
        hydrate_dynamic_item(
            source,
            cookie="test-cookie",
            fetch_detail=fetch_detail,
        )
    )

    assert hydrated == source
    assert dynamic_content(hydrated) == ""


def test_service_backfills_recent_empty_body_without_changing_delivery_state(
    tmp_path: Path,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    source = _item()
    snapshot = build_dynamic_history_snapshot(
        source,
        pub_ts=int(time.time()),
        author_mid=SEER_UID,
        pushed=True,
    )
    service.history.save_snapshot(snapshot)
    service.cookie_store.save("test-cookie")

    async def fetch_detail(_cookie: str, _dynamic_id: str) -> BiliFeedResponse:
        return _detail_response(_item(body="补全后的官方正文"))

    service.fetch_detail = fetch_detail

    assert asyncio.run(service.backfill_recent_empty_bodies()) == 1
    saved = service.history.get("123456")
    assert saved is not None
    assert saved.pushed
    assert dynamic_content(saved.item) == "补全后的官方正文"
    assert asyncio.run(service.backfill_recent_empty_bodies()) == 0
