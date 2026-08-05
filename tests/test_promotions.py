from __future__ import annotations

import pytest

from ironsbot.config.models.ai import AiConfig
from ironsbot.config.models.settings import Settings
from ironsbot.core.messaging import AiIntentAction
from ironsbot.core.promotions import PromotionCatalog, PromotionConfig


def _promotion_action(promotion: str = "manual") -> AiIntentAction:
    return AiIntentAction(
        feature="ai_intent_fire_manual",
        keywords=["手册"],
        action="promotion",
        promotion=promotion,
        intent="判断用户是否索要手册链接。",
    )


def test_promotion_catalog_renders_configured_url() -> None:
    promotion = PromotionConfig(
        feature="fire_manual_ad",
        url="https://example.com/manual",
        text="说明：{url}",
        append_to_push=True,
    )

    catalog = PromotionCatalog({"manual": promotion})

    assert catalog.require("manual").message == "说明：https://example.com/manual"
    assert catalog.push_promotions == (promotion,)


def test_settings_rejects_promotion_with_unknown_feature() -> None:
    with pytest.raises(ValueError, match="is not registered"):
        Settings(
            promotions={
                "manual": PromotionConfig(
                    feature="not_a_feature",
                    text="说明：{url}",
                )
            }
        )


def test_settings_requires_enabled_promotion_action_to_reference_promotion() -> None:
    with pytest.raises(ValueError, match="is not an enabled promotion"):
        Settings(
            ai=AiConfig(
                intent_actions={"manual": _promotion_action()}
            )
        )


def test_settings_accepts_explicit_promotion_action() -> None:
    settings = Settings(
        promotions={
            "manual": PromotionConfig(
                feature="fire_manual_ad",
                text="说明：{url}",
            )
        },
        ai=AiConfig(intent_actions={"manual": _promotion_action()}),
    )

    assert settings.ai.intent_actions["manual"].promotion == "manual"
