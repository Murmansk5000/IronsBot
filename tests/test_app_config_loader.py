import re
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from ironsbot.config.loader import CONFIG_ENV, load_settings
from ironsbot.config.models.messaging import (
    BotRoutingConfig,
    CommandCooldownConfig,
    CommandMessageAction,
    GroupScheduledMessageAction,
    MessageConfig,
    OutboundRateLimitConfig,
    OutboundRateLimitWindowConfig,
    PrivateScheduledMessageAction,
    PushUnsubscribeConfig,
    TeamAuditWelcomeConfig,
)
from ironsbot.config.models.operations import DockerUpdateConfig
from ironsbot.config.models.seer import (
    RankPageRefreshConfig,
    TeamResourceConfig,
)
from ironsbot.config.models.settings import MatcherPriorityConfig, Settings
from ironsbot.core.bilibili import DEFAULT_BILI_ACCOUNT_UID

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AI_CHAT_PRIORITY = 200
HEADLESS_USER_ID = 12345678
DEFAULT_OUTBOUND_MAX_MESSAGES = 10
DEFAULT_HELP_HINT_MAX_PER_WINDOW = 3
DEFAULT_RENDER_CACHE_MAX_SIZE_MB = 200
DEFAULT_DOCKER_UPDATE_TIMEOUT_SECONDS = 300.0
DEFAULT_RANK_DISPLAY_LIMIT = 10
DEFAULT_RANK_MAX_DISPLAY_LIMIT = 100
DEFAULT_RANK_STALE_AGE_WEIGHT = 0.08
DEFAULT_RANK_STALE_AGE_MAX_MULTIPLIER = 5.0
DEFAULT_RANK_REFRESH_PAGES_PER_RUN_MIN = 1
DEFAULT_RANK_REFRESH_INTERVAL_MINUTES = 15
DEFAULT_RANK_REFRESH_INTERVAL_OFFSET_MINUTES = 4
DEFAULT_RANK_REFRESH_SCHEDULE_JITTER_SECONDS = 240
DEFAULT_RANK_REFRESH_REQUEST_INTERVAL_SECONDS = 3.0
DEFAULT_RANK_REFRESH_REQUEST_JITTER_SECONDS = 3.0
DEFAULT_AUTOCARD_SCORE_CUTOFF = 1000
DEFAULT_TEAM_AUDIT_FOLLOWUP_HOURS = 24.0
DEFAULT_TEAM_AUDIT_FINAL_FOLLOWUP_HOURS = 48.0
DEFAULT_SEER_PLAYER_PRIORITY = 10
MAIN_BOT_ID = 111111111
DEFAULT_PUSH_UNSUBSCRIBE_DATA_PATH = (
    "data/messaging/push_unsubscriptions.sqlite"
)
DEFAULT_RED_PACKET_NOTICE_COOLDOWN = 60.0
TEAM_RESOURCE_THRESHOLD = 2000
ACTIVE_CONFIG_SURFACE_PATHS = (
    ROOT / ".env.example",
    ROOT / "config.example.toml",
    ROOT / "templates" / "ironsbot.xml",
    ROOT / "docker-compose.yml",
)
PUBLIC_TEXT_PATHS = (
    *ACTIVE_CONFIG_SURFACE_PATHS,
    ROOT / "README.md",
    ROOT / "docker" / "README.md",
)
STALE_ACTIVE_CONFIG_PATTERNS = (
    r"\buid_modes\b",
    r"\bdefault_mode\b",
    r"\bdefault_accounts\b",
    r"\bextra_accounts\b",
    r"\baccount_aliases\b",
    r"\baccount_modes\b",
    r"\bprivate_unsubscribe\b",
    r"\bteam_shortcut\b",
    r"\bactivity_link_push\b",
    r"\bactivity_link_daily",
    r"\baction_templates\b",
    r"\bdefault_uids\b",
    r"\bextra_uids\b",
    r"\bfire_manual_intent\b",
)
STALE_PUBLIC_TEXT_PATTERNS = (
    r"README\.old",
    r"旧榜单",
    r"db\s*(?:与|和)\s*image\s*模块",
    r"seer_rank`\s*/\s*`rank",
    r"TOML 使用宽松加载",
    r"配置迁移",
    r"Behavior Config Migration",
    r"ignored with warning",
)


def _load_module_from_path(name: str, path: Path) -> ModuleType:
    spec = spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assert_default_push_unsubscribe(
    push_unsubscribe: PushUnsubscribeConfig,
) -> None:
    assert (
        push_unsubscribe.commands,
        push_unsubscribe.restore_commands,
        push_unsubscribe.data_path,
    ) == (
        ["td", "退订"],
        ["订阅", "恢复订阅", "推送管理"],
        DEFAULT_PUSH_UNSUBSCRIBE_DATA_PATH,
    )
    assert "TD" in push_unsubscribe.hint
    assert "可查看本群推送订阅" in push_unsubscribe.group_hint


def _assert_default_docker_update(docker_update: DockerUpdateConfig) -> None:
    assert docker_update.check_on_startup
    assert docker_update.check_on_restart
    assert docker_update.image == "murmansk5000/ironsbot:latest"
    assert docker_update.container_name == "ironsbot"
    assert docker_update.docker_socket_path == "/var/run/docker.sock"
    assert docker_update.watchtower_image == "containrrr/watchtower:latest"
    assert docker_update.watchtower_docker_api_version == "1.40"
    assert docker_update.timeout_seconds == DEFAULT_DOCKER_UPDATE_TIMEOUT_SECONDS


def _assert_example_bot_routing(config: Settings) -> None:
    routing = config.messaging.bot_routing
    assert not routing.enabled
    assert routing.default_bot == "main_bot"
    assert routing.bot_aliases == {
        "main_bot": MAIN_BOT_ID,
        "backup_bot": 222222222,
    }
    assert routing.groups == {
        "group_a": "main_bot",
        "group_b": "backup_bot",
    }
    assert routing.users == {
        "owner": "main_bot",
        "user_a": "backup_bot",
    }


def _assert_default_team_audit_welcome(config: Settings) -> None:
    team_audit = config.messaging.team_audit_welcome
    assert not team_audit.enabled
    assert "米米号" in team_audit.message
    assert team_audit.followup_enabled
    assert team_audit.followup_after_hours == DEFAULT_TEAM_AUDIT_FOLLOWUP_HOURS
    assert "退出本审核群" in team_audit.followup_message
    assert team_audit.final_followup_enabled
    assert (
        team_audit.final_followup_after_hours
        == DEFAULT_TEAM_AUDIT_FINAL_FOLLOWUP_HOURS
    )
    assert "仍然还在审核群" in team_audit.final_followup_message
    assert team_audit.followup_cache_path == "data/team_audit_welcome/pending.sqlite"


@pytest.mark.parametrize("field", ["feature", "groups"])
def test_team_audit_rejects_removed_target_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        TeamAuditWelcomeConfig.model_validate({field: "team_audit"})


def _assert_default_matcher_priorities(
    matcher_priority: MatcherPriorityConfig,
) -> None:
    assert matcher_priority.seer_query < matcher_priority.ai_chat
    assert matcher_priority.ai_group_at < 0
    assert matcher_priority.ai_mention_guard < 0
    assert matcher_priority.ai_chat == DEFAULT_AI_CHAT_PRIORITY
    assert matcher_priority.seer_player == DEFAULT_SEER_PLAYER_PRIORITY
    assert matcher_priority.sendpic < matcher_priority.seer_pet
    assert matcher_priority.sendpic < matcher_priority.seer_mintmark
    assert matcher_priority.seer_pet > matcher_priority.seer_rank
    assert matcher_priority.seer_mintmark > matcher_priority.seer_rank
    priorities = matcher_priority.model_dump()
    non_negative_priorities = [value for value in priorities.values() if value >= 0]
    assert len(non_negative_priorities) == len(set(non_negative_priorities))


def _assert_example_rank_page_refresh(config: RankPageRefreshConfig) -> None:
    assert "群星牌" in config.rank_keys
    assert "竞技段位" in config.rank_keys
    assert "狂野段位" in config.rank_keys
    assert "专家段位" in config.rank_keys
    assert config.target_limits == {}
    assert config.score_cutoffs["群星牌"] == DEFAULT_AUTOCARD_SCORE_CUTOFF
    assert config.stale_age_weight == DEFAULT_RANK_STALE_AGE_WEIGHT
    assert config.stale_age_max_multiplier == DEFAULT_RANK_STALE_AGE_MAX_MULTIPLIER
    assert config.pages_per_run_min == DEFAULT_RANK_REFRESH_PAGES_PER_RUN_MIN
    assert config.interval_minutes == DEFAULT_RANK_REFRESH_INTERVAL_MINUTES
    assert (
        config.interval_offset_minutes
        == DEFAULT_RANK_REFRESH_INTERVAL_OFFSET_MINUTES
    )
    assert (
        config.schedule_jitter_seconds
        == DEFAULT_RANK_REFRESH_SCHEDULE_JITTER_SECONDS
    )
    assert (
        config.request_interval_seconds
        == DEFAULT_RANK_REFRESH_REQUEST_INTERVAL_SECONDS
    )
    assert (
        config.request_jitter_seconds
        == DEFAULT_RANK_REFRESH_REQUEST_JITTER_SECONDS
    )
    assert config.active_start == "07:30"
    assert config.active_end == "01:30"
    assert config.times == []


def test_example_config_parses() -> None:
    config = load_settings(ROOT / "config.example.toml")

    assert config.features.superuser_bypass
    assert config.features.group_aliases == {
        "group_a": 987654321,
        "group_b": 876543210,
    }
    assert config.features.user_aliases == {
        "owner": 1234567890,
        "user_a": 2345678901,
    }
    assert config.ai.model == "deepseek-v4-pro"
    assert "fire_manual" in config.ai.intent_actions
    assert "fire_manual_intent" not in config.ai.intent_actions
    assert config.bilibili.accounts["seer"] == DEFAULT_BILI_ACCOUNT_UID
    assert config.bilibili.account_nicknames["seer"] == "赛尔号官方"
    assert config.bilibili.push.mode == "link"
    assert config.bilibili.push.accounts == ["seer"]
    assert config.bilibili.push.modes == {"seer": "full"}
    assert config.bilibili.polling.windows[0].start == "07:00"
    assert "恭喜" in config.bilibili.filters.suppress_push_patterns
    assert config.messaging.meeting.commands == ["开播", "会议"]
    _assert_default_push_unsubscribe(config.messaging.push_unsubscribe)
    assert config.messaging.red_packet_notice.enabled
    assert (
        config.messaging.red_packet_notice.cooldown_seconds
        == DEFAULT_RED_PACKET_NOTICE_COOLDOWN
    )
    _assert_default_team_audit_welcome(config)
    assert config.seer.team_resource.commands == ["战队"]
    assert (
        config.seer.team_resource.subscription_path.as_posix()
        == "data/seer/team_resource_subscriptions.sqlite"
    )
    assert "autocard" in config.seer.player.sections
    assert config.seer.rank.display_limit == DEFAULT_RANK_DISPLAY_LIMIT
    assert config.seer.rank.max_display_limit == DEFAULT_RANK_MAX_DISPLAY_LIMIT
    assert config.seer.rank.display_limits == {}
    _assert_example_rank_page_refresh(config.seer.rank.page_refresh)
    assert config.seer.season.autocard_name == "群星牌赛季"
    assert config.seer.season.autocard_start_time is None
    assert config.seer.season.autocard_end_time is None
    assert config.operations.data_sync.on_startup
    _assert_example_bot_routing(config)
    assert not config.operations.data_sync.startup_trigger_remote_build
    assert config.operations.data_sync.sources["seerapi"].local_path
    assert config.operations.data_sync.sources["seerapi"].remote_build.enabled
    _assert_default_docker_update(config.operations.docker_update)
    assert not config.bot.logging.file_enabled
    assert config.paths.log_file == Path("logs/ironsbot.log")
    assert not config.bot.logging.error_file_enabled
    assert config.paths.error_log_file == Path("logs/ironsbot.error.log")
    _assert_default_matcher_priorities(config.bot.matcher_priority)
    remote_build_steps = config.operations.data_sync.sources[
        "seerapi"
    ].remote_build.steps
    assert [step.name for step in remote_build_steps] == [
        "refresh_official_sources",
        "refresh_unity_config",
        "sync_config_sources",
        "build_api_data",
        "build_ironsbot_data",
    ]
    assert (
        remote_build_steps[-1].repository
        == "Murmansk-Seer/seerapi"
    )
    assert (
        remote_build_steps[-1].workflow_id
        == "build-ironsbot-data-db.yml"
    )
    assert remote_build_steps[0].inputs == {
        "force-update-assets": False,
        "force-update-config": False,
        "dispatch-api-data": False,
    }
    assert remote_build_steps[1].inputs == {}
    assert remote_build_steps[2].inputs == {"force": False}
    assert remote_build_steps[3].inputs == {
        "debug_enabled": False,
        "force": False,
    }
    assert remote_build_steps[4].inputs == {"force": False}
    assert config.features.help.ignored_plugins == []


def test_example_config_has_no_unknown_fields() -> None:
    assert isinstance(load_settings(ROOT / "config.example.toml", env={}), Settings)


def test_scheduled_push_requires_stable_id() -> None:
    with pytest.raises(ValidationError, match="定时推送必须配置非空 id"):
        PrivateScheduledMessageAction(
            message="私聊定时推送",
            hour=23,
        )

    with pytest.raises(ValidationError, match="只能包含英文字母"):
        PrivateScheduledMessageAction(
            id="每日 提醒",
            message="私聊定时推送",
            hour=23,
        )


def test_scheduled_push_ids_are_globally_unique() -> None:
    with pytest.raises(ValidationError, match="定时推送 id 必须全局唯一: daily"):
        MessageConfig(
            private_schedules=[
                PrivateScheduledMessageAction(
                    id="daily",
                    message="私聊定时推送",
                    hour=23,
                )
            ],
            group_schedules=[
                GroupScheduledMessageAction(
                    id="daily",
                    message="群聊定时推送",
                    hour=23,
                )
            ],
        )


def test_dynamic_message_commands_require_stable_ids() -> None:
    with pytest.raises(
        ValidationError,
        match="command message action requires a non-empty id",
    ):
        CommandMessageAction(
            commands=["hello"],
            message="world",
        )

    with pytest.raises(
        ValidationError,
        match="command message action id may only contain",
    ):
        CommandMessageAction(
            id="daily reminder",
            commands=["hello"],
            message="world",
        )


def test_outbound_rate_limit_requires_distinct_nonempty_windows() -> None:
    with pytest.raises(
        ValidationError,
        match=r"outbound_rate_limit\.windows must not be empty",
    ):
        OutboundRateLimitConfig(windows=[])

    window = OutboundRateLimitWindowConfig(
        window_seconds=60,
        max_messages=10,
    )
    with pytest.raises(
        ValidationError,
        match=r"contains duplicate window_seconds",
    ):
        OutboundRateLimitConfig(windows=[window, window])


def test_command_cooldown_rejects_unknown_message_placeholders() -> None:
    with pytest.raises(
        ValidationError,
        match=r"only supports \{remaining_seconds\}",
    ):
        CommandCooldownConfig(cooldown_message="{unknown}")


def test_bot_routing_config_accepts_aliases_and_numeric_bot_ids() -> None:
    config = BotRoutingConfig(
        enabled=True,
        default_bot="main_bot",
        bot_aliases={"main_bot": MAIN_BOT_ID},
        groups={"group_a": "main_bot", "987654321": MAIN_BOT_ID},
        users={"owner": "111111111"},
    )

    assert config.resolve_bot_reference("main_bot") == MAIN_BOT_ID
    assert config.resolve_bot_reference(str(MAIN_BOT_ID)) == MAIN_BOT_ID


def test_bot_routing_config_rejects_unknown_bot_alias() -> None:
    with pytest.raises(
        ValidationError,
        match=r"messaging\.bot_routing\.groups\.group_a",
    ):
        BotRoutingConfig(
            enabled=True,
            bot_aliases={"main_bot": MAIN_BOT_ID},
            groups={"group_a": "missing_bot"},
        )


def test_active_config_surfaces_do_not_reference_stale_fields() -> None:
    stale_matches: list[str] = []

    for path in ACTIVE_CONFIG_SURFACE_PATHS:
        text = path.read_text(encoding="utf-8")
        stale_matches.extend(
            f"{path.relative_to(ROOT)}: {pattern}"
            for pattern in STALE_ACTIVE_CONFIG_PATTERNS
            if re.search(pattern, text)
        )

    assert stale_matches == []


def test_public_text_does_not_reference_stale_structures() -> None:
    stale_matches: list[str] = []

    for path in PUBLIC_TEXT_PATHS:
        text = path.read_text(encoding="utf-8")
        stale_matches.extend(
            f"{path.relative_to(ROOT)}: {pattern}"
            for pattern in STALE_PUBLIC_TEXT_PATTERNS
            if re.search(pattern, text)
        )

    assert stale_matches == []


def test_rank_page_refresh_interval_offset_must_be_smaller_than_interval() -> None:
    with pytest.raises(ValidationError):
        RankPageRefreshConfig(interval_minutes=10, interval_offset_minutes=10)


def test_rank_page_refresh_min_pages_must_not_exceed_max_pages() -> None:
    with pytest.raises(ValidationError):
        RankPageRefreshConfig(pages_per_run=2, pages_per_run_min=3)


def test_rank_page_refresh_active_window_requires_start_and_end() -> None:
    with pytest.raises(ValidationError):
        RankPageRefreshConfig(active_start="07:30")


def test_missing_app_config_fails_without_mutating_disk(tmp_path: Path) -> None:
    config_path = tmp_path / "config" / "ironsbot.toml"
    with pytest.raises(FileNotFoundError):
        load_settings(config_path, env={})
    assert not config_path.exists()


def test_config_path_is_selected_by_single_environment_variable() -> None:
    config = load_settings(
        env={CONFIG_ENV: str(ROOT / "config.example.toml")}
    )
    assert config.ai.model == "deepseek-v4-pro"


def test_unknown_app_config_fields_are_rejected_with_exact_path(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[[messaging.group_commands]]
id = "hello"
commands = ["hello"]
message = "world"
feature = "text_push"
unknown_command_field = true
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc_info:
        load_settings(config_path)

    assert (
        exc_info.value.errors()[0]["loc"]
        == ("messaging", "group_commands", 0, "unknown_command_field")
    )


def test_unregistered_feature_policy_is_rejected_with_exact_path(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[features.group_policy]
main = ["seer_player", "rank"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc_info:
        load_settings(config_path)

    assert exc_info.value.errors()[0]["loc"] == ("features",)
    assert "features.group_policy.main[1]=rank" in str(exc_info.value)


def test_unknown_bilibili_account_is_rejected_with_exact_path(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[bilibili.push.groups.main]
accounts = ["missing_account"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc_info:
        load_settings(config_path)

    assert exc_info.value.errors()[0]["loc"] == ("bilibili",)
    assert (
        "bilibili.push.groups.main.accounts[0]" in str(exc_info.value)
    )


def test_unknown_seer_section_is_rejected_with_exact_path(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[seer.player]
sections = ["basic", "unknown_section"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc_info:
        load_settings(config_path)

    assert exc_info.value.errors()[0]["loc"] == ("seer", "player", "sections")
    assert "seer.player.sections contains unknown section(s)" in str(exc_info.value)


def test_player_binding_path_loads(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[seer.player.binding]
path = "data/custom-player-bindings.sqlite"
""".strip(),
        encoding="utf-8",
    )

    config = load_settings(config_path)

    assert config.seer.player.binding.path == Path(
        "data/custom-player-bindings.sqlite"
    )


def test_incomplete_unknown_ai_action_is_rejected_with_exact_path(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[ai.intent_actions.custom_action]
enabled = true
message = "hello"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc_info:
        load_settings(config_path)

    assert exc_info.value.errors()[0]["loc"] == ("ai",)
    assert "ai.intent_actions.custom_action:" in str(exc_info.value)
    assert "unknown AI intent action must configure" in str(exc_info.value)


def test_invalid_app_config_field_values_still_fail(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[seer.rank]
display_limit = "not an integer"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_settings(config_path)


def test_team_resource_config_accepts_runtime_subscription_defaults() -> None:
    config = TeamResourceConfig(
        times="08:30,23:00",  # type: ignore[arg-type]
        default_threshold=TEAM_RESOURCE_THRESHOLD,
        default_at_users="owner,1234567890",  # type: ignore[arg-type]
    )

    assert config.times == ["08:30", "23:00"]
    assert config.default_threshold == TEAM_RESOURCE_THRESHOLD
    assert config.default_at_users == ["owner", "1234567890"]


def test_environment_secrets_are_injected_into_single_settings_tree() -> None:
    env = {
        "ONEBOT_ACCESS_TOKEN": "token",
        "AI_KEY": "sk-test",
        "SENDPIC_CNB_TOKEN": "cnb-token",
        "GITHUB_WORKFLOW_TOKEN": "gh-token",
        "HEADLESS_SEER_USER_ID": str(HEADLESS_USER_ID),
        "HEADLESS_SEER_PASSWORD": "md5",
    }

    settings = load_settings(ROOT / "config.example.toml", env=env)

    assert settings.bot.onebot_token == "token"
    assert settings.ai.api_key == "sk-test"
    assert settings.messaging.sendpic.cnb_token == "cnb-token"
    assert settings.operations.data_sync.github_token == "gh-token"
    assert settings.operations.headless.user_id == HEADLESS_USER_ID
    assert settings.operations.headless.password == "md5"


def test_app_config_defaults_cover_runtime_services() -> None:
    app_config = load_settings(ROOT / "config.example.toml")

    assert app_config.ai.model == "deepseek-v4-pro"
    assert app_config.ai.intent_actions
    assert app_config.seer.team_resource.commands == ["战队"]
    assert (
        app_config.features.help.hint_max_per_window
        == DEFAULT_HELP_HINT_MAX_PER_WINDOW
    )
    assert app_config.activity.lead_hours == [11, 1]
    assert "seerapi" in app_config.operations.data_sync.sources
    assert (
        app_config.messaging.outbound_rate_limit.windows[0].max_messages
        == DEFAULT_OUTBOUND_MAX_MESSAGES
    )
    assert app_config.messaging.meeting.commands == ["开播", "会议"]
    assert "aliases" in app_config.operations.data_sync.sources
    assert app_config.features.priority.enabled
    assert app_config.paths.render_cache == Path("render_cache")
    assert (
        app_config.seer.render.cache_max_size_mb
        == DEFAULT_RENDER_CACHE_MAX_SIZE_MB
    )
