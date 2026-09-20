import pytest

from ironsbot.config.models.ai import (
    DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS,
    PROMOTION_REQUIRED_ERROR,
    TEAM_RECOMMEND_LEGACY_MESSAGE_ERROR,
    TEAM_RECOMMEND_MESSAGES_REQUIRED_ERROR,
    UNKNOWN_AI_ACTION_ERROR,
    AiConfig,
)
from ironsbot.core.messaging import AiIntentAction

DEFAULT_AI_ACTION_COUNT = 0


def test_default_ai_actions_include_only_safe_builtin_actions() -> None:
    actions = list(AiConfig().intent_actions.values())

    assert len(actions) == DEFAULT_AI_ACTION_COUNT


def test_fire_manual_action_uses_generic_promotion_delivery() -> None:
    action = AiConfig(
        intent_actions={
            "fire_manual": AiIntentAction(
                feature="ai_intent_fire_manual",
                keywords=["手册"],
                action="promotion",
                promotion="fire_manual",
                intent="判断用户是否索要手册链接。",
            )
        }
    ).intent_actions["fire_manual"]

    assert action.feature == "ai_intent_fire_manual"
    assert action.keywords == ["手册"]
    assert action.action == "promotion"
    assert action.promotion == "fire_manual"
    assert action.intent == "判断用户是否索要手册链接。"


def test_team_recommend_requires_explicit_delivery_messages() -> None:
    with pytest.raises(ValueError) as exc_info:
        AiConfig(intent_actions={"team_recommend": AiIntentAction(enabled=True)})

    assert TEAM_RECOMMEND_MESSAGES_REQUIRED_ERROR in str(exc_info.value)


def test_admin_notice_defaults_live_in_ai_config() -> None:
    config = AiConfig()

    assert (
        config.admin_notice_cooldown_seconds == DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS
    )


def test_configured_actions_override_builtin_actions_by_id() -> None:
    actions = AiConfig(
        intent_actions={
            "team_recommend": AiIntentAction(
                messages=["自定义链接", "自定义群号"],
            )
        }
    )

    assert set(actions.intent_actions) == {"team_recommend"}
    assert actions.intent_actions["team_recommend"].messages == [
        "自定义链接",
        "自定义群号",
    ]


def test_disabled_custom_action_does_not_require_delivery_fields() -> None:
    action = AiConfig(
        intent_actions={"disabled": AiIntentAction(enabled=False)}
    ).intent_actions["disabled"]

    assert not action.enabled


def test_promotion_action_requires_a_promotion_id() -> None:
    with pytest.raises(ValueError) as exc_info:
        AiConfig(
            intent_actions={
                "custom": AiIntentAction(
                    keywords=["测试"],
                    action="promotion",
                )
            }
        )

    assert PROMOTION_REQUIRED_ERROR in str(exc_info.value)


def test_team_recommend_rejects_legacy_single_message() -> None:
    with pytest.raises(ValueError) as exc_info:
        AiConfig(
            intent_actions={"team_recommend": AiIntentAction(message="旧单条回复")}
        )

    assert TEAM_RECOMMEND_LEGACY_MESSAGE_ERROR in str(exc_info.value)


def test_custom_action_requires_complete_definition() -> None:
    with pytest.raises(ValueError) as exc_info:
        AiConfig(intent_actions={"custom": AiIntentAction()})

    error = str(exc_info.value)
    assert "ai.intent_actions.custom" in error
    assert UNKNOWN_AI_ACTION_ERROR in error


def test_custom_action_requires_explicit_action() -> None:
    with pytest.raises(ValueError) as exc_info:
        AiConfig(intent_actions={"custom": AiIntentAction(keywords=["测试"])})

    error = str(exc_info.value)
    assert "ai.intent_actions.custom" in error
    assert UNKNOWN_AI_ACTION_ERROR in error
