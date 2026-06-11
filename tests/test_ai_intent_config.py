from ironsbot.shared.config.config import (
    DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS,
    DEFAULT_AI_MENTION_GUARD_MESSAGE,
    DEFAULT_AI_MENTION_GUARD_REPLY_MAX_PER_WINDOW,
    DEFAULT_AI_MENTION_GUARD_REPLY_WINDOW_SECONDS,
    DEFAULT_JOIN_TEAM_MESSAGE,
    AiConfig,
    resolve_configured_actions,
)


def test_default_join_team_action_sends_audit_group_link() -> None:
    actions = resolve_configured_actions(AiConfig())

    assert len(actions) == 1
    action = actions[0]
    assert action.template == "join_team"
    assert action.keywords == ["战队"]
    assert action.action == "message"
    assert action.message == DEFAULT_JOIN_TEAM_MESSAGE
    assert "group_code=719544559" in action.message


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
    assert config.mention_guard_message == DEFAULT_AI_MENTION_GUARD_MESSAGE
    assert (
        config.admin_notice_cooldown_seconds
        == DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS
    )
