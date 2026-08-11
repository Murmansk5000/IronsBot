from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ironsbot.core.bilibili import BiliConfig
from ironsbot.services.bilibili.categories import classify_seer_dynamic


def _item(text: str) -> dict[str, Any]:
    return {
        "modules": {"module_dynamic": {"major": {"opus": {"summary": {"text": text}}}}}
    }


def _timestamp(day: int, hour: int, minute: int) -> int:
    return int(
        datetime(
            2026, 8, day, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai")
        ).timestamp()
    )


def test_seer_dynamic_classification_supports_multiple_categories() -> None:
    categories = classify_seer_dynamic(
        _item("新版本即将到来，查看下方长图：全新精灵和全新皮肤即将登场。"),
        pub_ts=_timestamp(3, 17, 30),
        config=BiliConfig().seer_categories,
    )

    assert categories == ("version_preview", "pet", "skin")


def test_seer_dynamic_classification_uses_preview_time_only_with_text_signal() -> None:
    config = BiliConfig().seer_categories.model_copy(
        update={"version_preview_patterns": []}
    )

    assert classify_seer_dynamic(
        _item("下周新版本的内容整理即将到来。"),
        pub_ts=_timestamp(3, 17, 30),
        config=config,
    ) == ("version_preview",)
    assert classify_seer_dynamic(
        _item("下周新版本的内容整理即将到来。"),
        pub_ts=_timestamp(2, 17, 30),
        config=config,
    ) == ("other",)
    assert classify_seer_dynamic(
        _item("今天的日常消息。"),
        pub_ts=_timestamp(3, 17, 30),
        config=config,
    ) == ("other",)


def test_seer_dynamic_classification_covers_gameplay_and_fallback_categories() -> None:
    config = BiliConfig().seer_categories

    assert classify_seer_dynamic(
        _item("群星牌大师赛直播开启，技能特效抢先看。"),
        pub_ts=_timestamp(3, 12, 0),
        config=config,
    ) == ("skill_showcase", "autocard", "competition")
    assert classify_seer_dynamic(
        _item("恭喜玩家中奖，请及时查看私信通知。"),
        pub_ts=_timestamp(3, 12, 0),
        config=config,
    ) == ("lottery",)


def test_seer_dynamic_classification_uses_short_topic_name() -> None:
    item = _item("")
    item["modules"]["module_dynamic"]["topic"] = {"name": "赛尔号巅峰之战"}

    assert classify_seer_dynamic(
        item,
        pub_ts=_timestamp(3, 12, 0),
        config=BiliConfig().seer_categories,
    ) == ("competition",)
