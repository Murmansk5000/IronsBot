import pytest

from ironsbot.config.models.ai import (
    DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS,
    DEFAULT_FIRE_MANUAL_INTENT,
    TEAM_RECOMMEND_LEGACY_MESSAGE_ERROR,
    UNKNOWN_AI_ACTION_ERROR,
    AiConfig,
)
from ironsbot.core.messaging import (
    DEFAULT_JOIN_TEAM_MESSAGES,
    FIRE_MANUAL_LINK_MESSAGE,
    FIRE_MANUAL_URL,
    AiIntentAction,
)

DEFAULT_AI_ACTION_COUNT = 2


def test_default_ai_actions_include_team_recommend_and_fire_manual() -> None:
    actions = list(AiConfig().intent_actions.values())

    assert len(actions) == DEFAULT_AI_ACTION_COUNT
    action = actions[0]
    assert action.id == "team_recommend"
    assert action.feature == "ai_intent_team_recommend"
    assert action.keywords == ["战队"]
    assert action.action == "team_recommend"
    assert action.messages == list(DEFAULT_JOIN_TEAM_MESSAGES)
    assert "group_code=719544559" in action.messages[0]
    assert action.messages[1] == "战队审核群号：719544559"

    manual_action = actions[1]
    assert manual_action.id == "fire_manual"
    assert manual_action.feature == "ai_intent_fire_manual"
    assert manual_action.keywords == ["手册"]
    assert manual_action.action == "message"
    assert manual_action.intent == DEFAULT_FIRE_MANUAL_INTENT
    assert manual_action.message == FIRE_MANUAL_LINK_MESSAGE
    assert FIRE_MANUAL_URL in manual_action.message


def test_admin_notice_defaults_live_in_ai_config() -> None:
    config = AiConfig()

    assert (
        config.admin_notice_cooldown_seconds
        == DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS
    )


def test_configured_actions_override_builtin_actions_by_id() -> None:
    actions = list(
        AiConfig(
            intent_actions={
                "team_recommend": AiIntentAction(
                    messages=["自定义链接", "自定义群号"],
                )
            }
        ).intent_actions.values()
    )

    assert [action.id for action in actions] == ["team_recommend", "fire_manual"]
    assert actions[0].messages == ["自定义链接", "自定义群号"]
    assert actions[1].message == FIRE_MANUAL_LINK_MESSAGE


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
