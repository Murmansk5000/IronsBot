import pytest

from ironsbot.config.models.ai import (
    DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS,
    DEFAULT_FIRE_MANUAL_INTENT,
    TEAM_RECOMMEND_LEGACY_MESSAGE_ERROR,
    TEAM_RECOMMEND_MESSAGES_REQUIRED_ERROR,
    UNKNOWN_AI_ACTION_ERROR,
    AiConfig,
)
from ironsbot.core.messaging import (
    FIRE_MANUAL_LINK_MESSAGE,
    FIRE_MANUAL_URL,
    AiIntentAction,
)

DEFAULT_AI_ACTION_COUNT = 1


def test_default_ai_actions_include_only_safe_builtin_actions() -> None:
    actions = list(AiConfig().intent_actions.values())

    assert len(actions) == DEFAULT_AI_ACTION_COUNT
    manual_action = actions[0]
    assert manual_action.id == "fire_manual"
    assert manual_action.feature == "ai_intent_fire_manual"
    assert manual_action.keywords == ["手册"]
    assert manual_action.action == "message"
    assert manual_action.intent == DEFAULT_FIRE_MANUAL_INTENT
    assert manual_action.message == FIRE_MANUAL_LINK_MESSAGE
    assert FIRE_MANUAL_URL in manual_action.message


def test_team_recommend_requires_explicit_delivery_messages() -> None:
    with pytest.raises(ValueError) as exc_info:
        AiConfig(intent_actions={"team_recommend": AiIntentAction(enabled=True)})

    assert TEAM_RECOMMEND_MESSAGES_REQUIRED_ERROR in str(exc_info.value)


def test_admin_notice_defaults_live_in_ai_config() -> None:
    config = AiConfig()

    assert (
        config.admin_notice_cooldown_seconds
        == DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS
    )


def test_configured_actions_override_builtin_actions_by_id() -> None:
    actions = AiConfig(
        intent_actions={
            "team_recommend": AiIntentAction(
                messages=["自定义链接", "自定义群号"],
            )
        }
    )

    assert set(actions.intent_actions) == {"team_recommend", "fire_manual"}
    assert actions.intent_actions["team_recommend"].messages == [
        "自定义链接",
        "自定义群号",
    ]
    assert actions.intent_actions["fire_manual"].message == FIRE_MANUAL_LINK_MESSAGE


def test_default_actions_can_be_disabled_explicitly() -> None:
    actions = list(
        AiConfig(
            intent_actions={"fire_manual": AiIntentAction(enabled=False)}
        ).intent_actions.values()
    )

    manual_action = next(
        action for action in actions if action.id == "fire_manual"
    )
    assert not manual_action.enabled


def test_team_recommend_rejects_legacy_single_message() -> None:
    with pytest.raises(ValueError) as exc_info:
        AiConfig(
            intent_actions={
                "team_recommend": AiIntentAction(message="旧单条回复")
            }
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
