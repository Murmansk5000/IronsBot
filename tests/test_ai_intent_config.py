from ironsbot.config.models.ai import (
    DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS,
    DEFAULT_AI_MENTION_GUARD_REPLY_MAX_PER_WINDOW,
    DEFAULT_AI_MENTION_GUARD_REPLY_WINDOW_SECONDS,
    DEFAULT_FIRE_MANUAL_INTENT,
    DEFAULT_JOIN_TEAM_MESSAGE,
    AiConfig,
    resolve_configured_actions,
)
from ironsbot.shared.promotions import (
    FIRE_MANUAL_LINK_MESSAGE,
    FIRE_MANUAL_URL,
)

DEFAULT_AI_ACTION_COUNT = 2


def test_default_ai_actions_include_join_team_and_fire_manual() -> None:
    actions = resolve_configured_actions(AiConfig())

    assert len(actions) == DEFAULT_AI_ACTION_COUNT
    action = actions[0]
    assert action.template == "join_team"
    assert action.keywords == ["战队"]
    assert action.action == "team_recommend"
    assert action.message == DEFAULT_JOIN_TEAM_MESSAGE
    assert "group_code=719544559" in action.message

    manual_action = actions[1]
    assert manual_action.template == "fire_manual"
    assert manual_action.feature == "fire_manual"
    assert manual_action.keywords == ["手册"]
    assert manual_action.action == "message"
    assert manual_action.intent == DEFAULT_FIRE_MANUAL_INTENT
    assert manual_action.message == FIRE_MANUAL_LINK_MESSAGE
    assert FIRE_MANUAL_URL in manual_action.message


def test_ai_mention_guard_defaults_live_in_ai_config() -> None:
    config = AiConfig()

    assert (
        config.mention_guard_reply_window_seconds
        == DEFAULT_AI_MENTION_GUARD_REPLY_WINDOW_SECONDS
    )
    assert (
        config.mention_guard_reply_max_per_window
        == DEFAULT_AI_MENTION_GUARD_REPLY_MAX_PER_WINDOW
    )
    assert (
        config.admin_notice_cooldown_seconds
        == DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS
    )
