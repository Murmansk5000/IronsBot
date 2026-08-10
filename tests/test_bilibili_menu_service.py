import asyncio
from pathlib import Path

from ironsbot.config.models.seer import ExternalReferencesConfig
from ironsbot.core.features import FeatureConfig
from ironsbot.integrations.storage.bilibili_history import (
    SqliteBiliDynamicHistoryStore,
)
from ironsbot.services.bilibili.dynamic_history import (
    DynamicHistoryRecord,
)
from ironsbot.services.bilibili.menu import (
    build_dynamic_detail_for_selection,
    build_dynamic_menu_text,
    dynamic_record_ids,
    select_cached_dynamic_id,
)
from ironsbot.services.bilibili.service import BiliFeedResponse
from ironsbot.services.seer.external_references import SeerInfoReferences
from tests.helpers.bilibili import build_test_bilibili_service


def _record(
    dynamic_id: str,
    *,
    pub_ts: int = 1781004683,
    suppressed: bool = False,
) -> DynamicHistoryRecord:
    return DynamicHistoryRecord(
        dynamic_id=dynamic_id,
        uid=1310714247,
        author_name="赛尔号",
        pub_ts=pub_ts,
        brief="测试动态",
        item={"id_str": dynamic_id},
        pushed=False,
        suppressed=suppressed,
        suppression_reason="命中规则：测试" if suppressed else "",
    )


def _save_record(
    history: SqliteBiliDynamicHistoryStore,
    record: DynamicHistoryRecord,
) -> None:
    history.save_item(
        record.item,
        pub_ts=record.pub_ts,
        author_mid=record.uid,
        author_name=record.author_name,
        brief=record.brief,
        pushed=record.pushed,
        suppressed=record.suppressed,
        suppression_reason=record.suppression_reason,
    )


def test_build_dynamic_menu_text_renders_records() -> None:
    text = build_dynamic_menu_text([_record("dynamic-1", suppressed=True)])

    assert "【最新动态列表】" in text
    assert "1. ⏰" in text
    assert "赛尔号（UID：1310714247）" in text
    assert "测试动态" in text
    assert "（未推送）" in text
    assert "两分钟内有效" not in text


def test_dynamic_record_ids_returns_cached_ids() -> None:
    assert dynamic_record_ids([_record("dynamic-1"), _record("dynamic-2")]) == [
        "dynamic-1",
        "dynamic-2",
    ]


def test_select_cached_dynamic_id_handles_statuses() -> None:
    ok = select_cached_dynamic_id(["a", "b"], "2")
    assert ok.status == "ok"
    assert ok.dynamic_id == "b"
    expected_count = 2
    assert ok.available_count == expected_count

    assert select_cached_dynamic_id([], "1").status == "expired"
    assert select_cached_dynamic_id(["a"], "x").status == "invalid"

    out_of_range = select_cached_dynamic_id(["a"], "2")
    assert out_of_range.status == "out_of_range"
    assert out_of_range.available_count == 1


def test_build_dynamic_detail_for_selection_renders_record(
    tmp_path: Path,
) -> None:
    history = SqliteBiliDynamicHistoryStore(tmp_path / "history.sqlite", 10)
    _save_record(history, _record("dynamic-1"))

    result = build_dynamic_detail_for_selection(
        history,
        ["dynamic-1"],
        "1",
    )

    assert result.status == "ok"
    assert result.record is not None
    assert result.available_count == 1
    assert result.record.dynamic_id == "dynamic-1"


def test_build_dynamic_detail_for_selection_handles_missing_record(
    tmp_path: Path,
) -> None:
    history = SqliteBiliDynamicHistoryStore(tmp_path / "history.sqlite", 10)
    result = build_dynamic_detail_for_selection(
        history,
        ["dynamic-1"],
        "1",
    )

    assert result.status == "missing"
    assert result.record is None


def test_bilibili_service_owns_dynamic_query_and_history(
    tmp_path: Path,
) -> None:
    service = build_test_bilibili_service(
        tmp_path,
        feature_config=FeatureConfig(
            group_policy={"1001": ["bili_query"]},
        ),
    )
    item = {
        "id_str": "dynamic-1",
        "modules": {
            "module_author": {
                "mid": 1310714247,
                "name": "赛尔号",
                "pub_ts": 1781004683,
            },
            "module_dynamic": {
                "major": {
                    "opus": {
                        "summary": {"text": "测试动态"},
                        "pics": [],
                    }
                }
            },
        },
    }

    async def fetch_feed(_cookie: str) -> BiliFeedResponse:
        return BiliFeedResponse(
            status_code=200,
            data={"code": 0, "data": {"items": [item]}},
        )

    service.fetch_feed = fetch_feed
    result = asyncio.run(service.query_dynamic_menu("group", 1001, 2001))

    assert result.status == "ok"
    assert result.dynamic_ids == ("dynamic-1",)
    assert "测试动态" in result.prompt
    assert service.select_dynamic(list(result.dynamic_ids), "1").status == "ok"


def test_bilibili_history_reference_is_added_only_when_enabled(
    tmp_path: Path,
) -> None:
    service = build_test_bilibili_service(
        tmp_path,
        external_references=SeerInfoReferences(ExternalReferencesConfig()),
    )

    assert "https://seerinfo.yuyuqaq.cn/bilibili" in service.history_reference_message(
        "📭 没有可展示的历史动态。"
    )

    disabled = build_test_bilibili_service(
        tmp_path / "disabled",
        external_references=SeerInfoReferences(
            ExternalReferencesConfig(bilibili_history=False)
        ),
    )
    assert disabled.history_reference_message("历史动态") == "历史动态"
