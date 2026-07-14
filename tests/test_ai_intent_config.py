import pytest

from ironsbot.config.models.ai import (
    DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS,
    DEFAULT_FIRE_MANUAL_INTENT,
    DEFAULT_JOIN_TEAM_MESSAGE,
    UNKNOWN_AI_ACTION_ERROR,
    AiConfig,
    AiIntentAction,
    resolve_configured_actions,
)
from ironsbot.shared.promotions import (
    FIRE_MANUAL_LINK_MESSAGE,
    FIRE_MANUAL_URL,
)

DEFAULT_AI_ACTION_COUNT = 2


def test_default_ai_actions_include_team_recommend_and_fire_manual() -> None:
    actions = resolve_configured_actions(AiConfig())

    assert len(actions) == DEFAULT_AI_ACTION_COUNT
    action = actions[0]
    assert action.id == "team_recommend"
    assert action.feature == "ai_intent_team_recommend"
    assert action.keywords == ["战队"]
    assert action.action == "team_recommend"
    assert action.message == DEFAULT_JOIN_TEAM_MESSAGE
    assert "group_code=719544559" in action.message

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
    actions = resolve_configured_actions(
        AiConfig(
            intent_actions={
                "team_recommend": AiIntentAction(
                    action="message",
                    message="自定义战队回复",
                )
            }
        )
    )

    assert [action.id for action in actions] == ["team_recommend", "fire_manual"]
    assert actions[0].message == "自定义战队回复"
    assert actions[1].message == FIRE_MANUAL_LINK_MESSAGE


def test_default_actions_can_be_disabled_explicitly() -> None:
    actions = resolve_configured_actions(
        AiConfig(intent_actions={"fire_manual": AiIntentAction(enabled=False)})
    )

    manual_action = next(
        action for action in actions if action.id == "fire_manual"
    )
    assert not manual_action.enabled


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
