from __future__ import annotations

from typing import Any

from ironsbot.core.bilibili import BiliAccountCategorySubscriptionConfig
from ironsbot.services.bilibili.categories import classify_dynamic


def _item(text: str) -> dict[str, Any]:
    return {
        "modules": {"module_dynamic": {"major": {"opus": {"summary": {"text": text}}}}}
    }


def test_dynamic_categories_match_every_configured_text_pattern() -> None:
    config = BiliAccountCategorySubscriptionConfig.model_validate(
        {
            "label": "赛尔动态",
            "categories": {
                "pet": {"label": "精灵", "patterns": ["精灵"]},
                "skin": {"label": "皮肤", "patterns": ["皮肤"]},
            },
        }
    )

    assert classify_dynamic(_item("全新精灵和皮肤即将登场"), config) == (
        "pet",
        "skin",
    )


def test_dynamic_categories_ignore_unmatched_text_and_disabled_config() -> None:
    config = BiliAccountCategorySubscriptionConfig.model_validate(
        {
            "label": "赛尔动态",
            "categories": {"pet": {"label": "精灵", "patterns": ["精灵"]}},
        }
    )

    assert classify_dynamic(_item("普通消息"), config) == ()
    assert classify_dynamic(_item("全新精灵"), None) == ()
