import asyncio
from pathlib import Path

from ironsbot.config.models.features import FeatureConfig
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.services.bilibili.content import DynamicContentCompactor
from ironsbot.services.bilibili.dynamic_history import (
    DynamicHistoryRecord,
)
from ironsbot.services.bilibili.menu import build_dynamic_menu_text, dynamic_record_ids
from ironsbot.services.bilibili.push import DynamicHistorySnapshot
from ironsbot.services.bilibili.service import BiliFeedResponse
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
                "mid": 912345678,
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
    result = asyncio.run(
        service.query_dynamic_menu(
            actor=ActorRef(Platform.ONEBOT, "2001"),
            conversation=ConversationRef(Platform.ONEBOT, "group", "1001"),
        )
    )

    assert result.status == "ok"
    assert result.dynamic_ids == ("dynamic-1",)
    assert "赛尔号（UID：912345678）" in result.prompt
    assert service.get_dynamic("dynamic-1") is not None
    assert service.get_dynamic("missing") is None


def test_history_detail_generates_and_reuses_persisted_summary(
    tmp_path: Path,
) -> None:
    summary_max_chars = 20
    service = build_test_bilibili_service(tmp_path)
    item = {
        "id_str": "dynamic-summary",
        "modules": {
            "module_dynamic": {
                "major": {"opus": {"summary": {"text": "完整原文" * 20}}}
            }
        },
    }
    service.history.save_snapshot(
        DynamicHistorySnapshot(
            item=item,
            pub_ts=1,
            author_mid=1310714247,
            author_name="赛尔号",
            brief="测试动态",
        )
    )
    calls = 0

    async def summarize(text: str, *, max_chars: int) -> str:
        nonlocal calls
        del text
        calls += 1
        assert max_chars == summary_max_chars
        return "生成后的摘要"

    service.content_compactor = DynamicContentCompactor(
        summarizer=summarize,
        content_max_chars=10,
        summary_max_chars=summary_max_chars,
        use_ai=True,
    )
    record = service.history.get("dynamic-summary")
    assert record is not None

    first = asyncio.run(service.prepare_dynamic_detail(record))
    second = asyncio.run(service.prepare_dynamic_detail(record))

    assert (
        first.content_override
        == second.content_override
        == ("本条动态文本过长，AI总结如下：\n生成后的摘要")
    )
    assert calls == 1
    saved = service.history.get("dynamic-summary")
    assert saved is not None
    assert saved.summary_generated_by_ai
