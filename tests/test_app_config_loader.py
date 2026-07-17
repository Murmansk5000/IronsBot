import re
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from ironsbot.config.loader import (
    CONFIG_EXAMPLE_PATH_ENV,
    ENV_EXAMPLE_PATH_ENV,
    clear_app_config_cache,
    load_app_config,
    load_credentials_config,
    load_deployment_config,
    load_secrets_config,
    parse_toml_file,
)
from ironsbot.config.models.app import AppConfig
from ironsbot.config.models.bilibili import DEFAULT_BILI_ACCOUNT_UID
from ironsbot.config.models.deployment import DeploymentConfig
from ironsbot.config.models.message import (
    GroupScheduledMessageAction,
    MessageConfig,
    PrivateScheduledMessageAction,
    PushUnsubscribeConfig,
)
from ironsbot.config.models.runtime import (
    BotRoutingConfig,
    DockerUpdateConfig,
    MatcherPriorityConfig,
)
from ironsbot.config.models.secrets import CredentialsConfig, SecretsConfig
from ironsbot.config.models.seer import (
    RankPageRefreshConfig,
    TeamResourceConfig,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AI_CHAT_PRIORITY = 200
HEADLESS_USER_ID = 12345678
DEPLOYMENT_PORT = 9090
SUPERUSER_ID = 123456789
DEFAULT_OUTBOUND_MAX_MESSAGES = 10
DEFAULT_HELP_HINT_MAX_PER_WINDOW = 3
DEFAULT_HEADLESS_HEARTBEAT_INTERVAL = 300.0
DEFAULT_PLAYER_TIMEOUT_SECONDS = 30
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
    ROOT / "ironsbot" / "plugins" / "seer_data" / "__init__.py",
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
)
CONFIG_MIGRATION_FIELDS = (
    "ai.reset_commands",
    "ai.mention_guard_reply_window_seconds",
    "ai.mention_guard_reply_max_per_window",
    "bilibili.push.default_mode",
    "bilibili.uids",
    "message.private_unsubscribe",
    "seer.render.clear_on_startup",
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


def _assert_example_bot_routing(config: AppConfig) -> None:
    routing = config.runtime.bot_routing
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


def _assert_default_team_audit_welcome(config: AppConfig) -> None:
    team_audit = config.message.team_audit_welcome
    assert not team_audit.enabled
    assert team_audit.feature == "team_audit"
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
    config = load_app_config(ROOT / "config.example.toml")

    assert config.feature.superuser_bypass
    assert config.feature.group_aliases == {
        "group_a": 987654321,
        "group_b": 876543210,
    }
    assert config.feature.user_aliases == {
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
    assert config.message.meeting.commands == ["开播", "会议"]
    _assert_default_push_unsubscribe(config.message.push_unsubscribe)
    assert config.message.red_packet_notice.enabled
    assert (
        config.message.red_packet_notice.cooldown_seconds
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
    assert config.runtime.data_sync.on_startup
    _assert_example_bot_routing(config)
    assert not config.runtime.data_sync.startup_trigger_remote_build
    assert config.runtime.data_sync.sources["seerapi"].local_path
    assert config.runtime.data_sync.sources["seerapi"].remote_build.enabled
    _assert_default_docker_update(config.runtime.docker_update)
    assert not config.runtime.logging.file_enabled
    assert config.runtime.logging.file_path == "logs/ironsbot.log"
    assert not config.runtime.logging.error_file_enabled
    assert config.runtime.logging.error_file_path == "logs/ironsbot.error.log"
    _assert_default_matcher_priorities(config.runtime.matcher_priority)
    remote_build_steps = config.runtime.data_sync.sources[
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
    assert config.runtime.help.ignored_plugins == []


def test_example_config_has_no_unknown_fields() -> None:
    AppConfig.model_validate(parse_toml_file(ROOT / "config.example.toml"))


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
        match=r"runtime\.bot_routing\.groups\.group_a",
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


def test_readme_documents_lenient_config_migration() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    for field in CONFIG_MIGRATION_FIELDS:
        assert f"`{field}`" in text


def test_rank_page_refresh_interval_offset_must_be_smaller_than_interval() -> None:
    with pytest.raises(ValidationError):
        RankPageRefreshConfig(interval_minutes=10, interval_offset_minutes=10)


def test_rank_page_refresh_min_pages_must_not_exceed_max_pages() -> None:
    with pytest.raises(ValidationError):
        RankPageRefreshConfig(pages_per_run=2, pages_per_run_min=3)


def test_rank_page_refresh_active_window_requires_start_and_end() -> None:
    with pytest.raises(ValidationError):
        RankPageRefreshConfig(active_start="07:30")


def test_missing_app_config_is_created_from_example(tmp_path: Path) -> None:
    config_path = tmp_path / "config" / "ironsbot.toml"
    config = load_app_config(
        config_path,
        env={
            CONFIG_EXAMPLE_PATH_ENV: str(ROOT / "config.example.toml"),
            ENV_EXAMPLE_PATH_ENV: str(ROOT / ".env.example"),
        },
    )

    assert config_path.exists()
    env_example_path = tmp_path / "config" / "ironsbot.env.example"
    assert env_example_path.exists()
    assert config.ai.model == "deepseek-v4-pro"
    assert "SPDX-License-Identifier" in config_path.read_text(encoding="utf-8")
    assert "ONEBOT_ACCESS_TOKEN" in env_example_path.read_text(encoding="utf-8")


def test_default_app_config_is_created_when_path_env_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    config = load_app_config(
        env={
            CONFIG_EXAMPLE_PATH_ENV: str(ROOT / "config.example.toml"),
            ENV_EXAMPLE_PATH_ENV: str(ROOT / ".env.example"),
        },
    )

    config_path = tmp_path / "config" / "ironsbot.toml"
    assert config_path.exists()
    assert (tmp_path / "config" / "ironsbot.env.example").exists()
    assert config.ai.model == "deepseek-v4-pro"


def test_unknown_app_config_fields_are_ignored_with_exact_path(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[[message.group_commands]]
id = "hello"
commands = ["hello"]
message = "world"
feature = "text_push"
unknown_command_field = true
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(config_path)

    assert config.message.group_commands[0].id == "hello"
    assert (
        "message.group_commands[0].unknown_command_field is not a recognized field"
        in caplog.text
    )


def test_unregistered_feature_policy_is_ignored_with_exact_path(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[feature.group_policy]
main = ["seer_player", "rank"]
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(config_path)

    assert config.feature.group_policy["main"] == ["seer_player"]
    assert "feature.group_policy.main contains unknown feature 'rank'" in caplog.text


def test_unknown_bilibili_account_is_ignored_with_exact_path(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[bilibili.push.groups.main]
accounts = ["missing_account"]
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(config_path)

    assert config.bilibili.push.groups["main"].accounts == []
    assert (
        "bilibili.push.groups.main.accounts[0] references unknown Bilibili account"
        in caplog.text
    )


def test_unknown_seer_section_is_ignored_with_exact_path(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[seer.player]
sections = ["basic", "unknown_section"]
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(config_path)

    assert config.seer.player.sections == ["basic"]
    assert "seer.player.sections contains unknown section(s)" in caplog.text


def test_player_binding_path_loads(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[seer.player.binding]
path = "data/custom-player-bindings.sqlite"
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(config_path)

    assert config.seer.player.binding.path == Path(
        "data/custom-player-bindings.sqlite"
    )


def test_incomplete_unknown_ai_action_is_ignored_with_exact_path(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
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

    config = load_app_config(config_path)

    assert "custom_action" not in config.ai.intent_actions
    assert "ai.intent_actions.custom_action is incomplete" in caplog.text


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
        load_app_config(config_path)


def test_dev_and_prod_configs_parse() -> None:
    assert load_app_config(ROOT / "config.dev.toml").feature.group_aliases == {}
    assert load_app_config(ROOT / "config.prod.toml").runtime.data_sync.on_startup
    assert (
        not load_app_config(ROOT / "config.prod.toml")
        .runtime.data_sync
        .startup_trigger_remote_build
    )


def test_team_resource_config_accepts_runtime_subscription_defaults() -> None:
    config = TeamResourceConfig(
        times="08:30,23:00",  # type: ignore[arg-type]
        default_threshold=TEAM_RESOURCE_THRESHOLD,
        default_at_users="owner,1234567890",  # type: ignore[arg-type]
    )

    assert config.times == ["08:30", "23:00"]
    assert config.default_threshold == TEAM_RESOURCE_THRESHOLD
    assert config.default_at_users == ["owner", "1234567890"]


def test_env_secrets_credentials_and_deployment_are_separate() -> None:
    env = {
        "ONEBOT_ACCESS_TOKEN": "token",
        "AI_KEY": "sk-test",
        "SENDPIC_CNB_TOKEN": "cnb-token",
        "GITHUB_WORKFLOW_TOKEN": "gh-token",
        "HEADLESS_SEER_USER_ID": str(HEADLESS_USER_ID),
        "HEADLESS_SEER_PASSWORD": "md5",
        "ENVIRONMENT": "dev",
        "PORT": str(DEPLOYMENT_PORT),
        "COMMAND_START": '["/",""]',
        "SUPERUSERS": f"[{SUPERUSER_ID}]",
    }

    secrets = load_secrets_config(env)
    credentials = load_credentials_config(env)
    deployment = load_deployment_config(env)

    assert isinstance(secrets, SecretsConfig)
    assert isinstance(credentials, CredentialsConfig)
    assert isinstance(deployment, DeploymentConfig)
    assert secrets.ai_key == "sk-test"
    assert secrets.github_workflow_token == "gh-token"
    assert credentials.headless_seer_user_id == HEADLESS_USER_ID
    assert deployment.port == DEPLOYMENT_PORT
    assert deployment.command_start == ["/", ""]
    assert deployment.superusers == [SUPERUSER_ID]


def test_small_plugin_config_accessors_read_app_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_app_config_cache()
    monkeypatch.setenv("APP_CONFIG_PATH", str(ROOT / "config.example.toml"))
    monkeypatch.setenv("AI_KEY", "sk-test")
    monkeypatch.setenv("SENDPIC_CNB_TOKEN", "cnb-token")
    monkeypatch.setenv("HEADLESS_SEER_USER_ID", str(HEADLESS_USER_ID))
    monkeypatch.setenv("HEADLESS_SEER_PASSWORD", "md5")

    ai_config = _load_module_from_path(
        "ai_config_for_app_config_test",
        ROOT / "ironsbot" / "services" / "ai" / "config.py",
    )
    ai_intent_service = _load_module_from_path(
        "ai_intent_service_for_app_config_test",
        ROOT / "ironsbot" / "services" / "ai" / "intent.py",
    )
    activity_config = _load_module_from_path(
        "activity_reminder_config_for_app_config_test",
        ROOT / "ironsbot" / "services" / "activity" / "config.py",
    )
    bili_config = _load_module_from_path(
        "bilibili_monitor_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "bilibili" / "config.py",
    )
    sendpic_config = _load_module_from_path(
        "sendpic_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "sendpic" / "config.py",
    )
    headless_config = _load_module_from_path(
        "headless_seer_config_for_app_config_test",
        ROOT / "ironsbot" / "integrations" / "headless_seer" / "config.py",
    )
    headless_notice_config = _load_module_from_path(
        "headless_seer_notice_config_for_app_config_test",
        ROOT / "ironsbot" / "services" / "headless_seer_notice" / "config.py",
    )
    meeting_config = _load_module_from_path(
        "meeting_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "meeting" / "config.py",
    )
    message_config = _load_module_from_path(
        "messaging_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "messaging" / "config.py",
    )
    server_status_config = _load_module_from_path(
        "server_status_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "server_status" / "config.py",
    )
    scheduled_restart_config = _load_module_from_path(
        "scheduled_restart_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "scheduled_restart" / "config.py",
    )
    startup_config = _load_module_from_path(
        "startup_notice_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "startup_notice" / "config.py",
    )
    team_resource_config = _load_module_from_path(
        "team_resource_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "team_resource_subscription" / "config.py",
    )

    try:
        app_config = load_app_config(ROOT / "config.example.toml")
        assert ai_config.get_ai_config().model == "deepseek-v4-pro"
        assert ai_config.get_ai_key() == "sk-test"
        assert ai_intent_service.get_configured_actions()
        assert ai_intent_service.get_team_resource_config().commands == ["战队"]
        assert (
            app_config.runtime.help.hint_max_per_window
            == DEFAULT_HELP_HINT_MAX_PER_WINDOW
        )
        assert activity_config.get_activity_config().lead_hours == [11, 1]
        assert bili_config.get_bili_config().polling.windows[0].start == "07:00"
        assert sendpic_config.get_sendpic_config().local_root.name == "sendpic"
        assert sendpic_config.get_sendpic_cnb_token() == "cnb-token"
        assert "seerapi" in app_config.runtime.data_sync.sources
        assert (
            headless_config.get_headless_config().heartbeat_interval
            == DEFAULT_HEADLESS_HEARTBEAT_INTERVAL
        )
        assert (
            headless_config.get_headless_credentials().headless_seer_user_id
            == HEADLESS_USER_ID
        )
        assert headless_notice_config.get_headless_notice_config().login_notice
        assert (
            message_config.get_message_config().outbound_rate_limit.max_messages
            == DEFAULT_OUTBOUND_MAX_MESSAGES
        )
        assert message_config.get_message_config().meeting.commands == [
            "开播",
            "会议",
        ]
        assert meeting_config.get_meeting_config().commands == ["开播", "会议"]
        assert startup_config.get_startup_config().message == "机器人已开启。"
        assert not server_status_config.get_server_status_config().broadcast
        assert (
            server_status_config.get_docker_update_config().image
            == "murmansk5000/ironsbot:latest"
        )
        assert not scheduled_restart_config.get_restart_config().enabled
        assert "aliases" in app_config.runtime.data_sync.sources
        assert app_config.runtime.priority.enabled
        assert team_resource_config.get_team_resource_config().commands == ["战队"]
    finally:
        clear_app_config_cache()


def test_seer_plugin_config_accessors_read_app_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_app_config_cache()
    monkeypatch.setenv("APP_CONFIG_PATH", str(ROOT / "config.example.toml"))

    seer_query_config = _load_module_from_path(
        "seer_query_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "seer" / "query" / "config.py",
    )
    from ironsbot.services.seer import render_cache as seer_render_cache

    try:
        assert (
            seer_query_config.get_player_query_config().timeout_seconds
            == DEFAULT_PLAYER_TIMEOUT_SECONDS
        )
        assert seer_query_config.get_local_rank_config().enabled
        assert (
            seer_query_config.get_rank_query_config().display_limit
            == DEFAULT_RANK_DISPLAY_LIMIT
        )
        assert (
            seer_query_config.get_rank_query_config().max_display_limit
            == DEFAULT_RANK_MAX_DISPLAY_LIMIT
        )
        assert (
            seer_render_cache.get_render_config().cache_max_size_mb
            == DEFAULT_RENDER_CACHE_MAX_SIZE_MB
        )
    finally:
        clear_app_config_cache()
