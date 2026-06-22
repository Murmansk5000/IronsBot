import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest

from ironsbot.config import (
    CredentialsConfig,
    DeploymentConfig,
    SecretsConfig,
    clear_app_config_cache,
    load_app_config,
    load_credentials_config,
    load_deployment_config,
    load_secrets_config,
)

ROOT = Path(__file__).resolve().parents[1]
HEADLESS_USER_ID = 12345678
DEPLOYMENT_PORT = 9090
SUPERUSER_ID = 123456789
DEFAULT_REPLY_MAX_LINES = 80
DEFAULT_OUTBOUND_MAX_MESSAGES = 10
DEFAULT_MENTION_GUARD_MAX_PER_WINDOW = 10
DEFAULT_HEADLESS_HEARTBEAT_INTERVAL = 300.0
DEFAULT_PLAYER_TIMEOUT_SECONDS = 30
DEFAULT_RENDER_CACHE_MAX_SIZE_MB = 200


def _load_module_from_path(name: str, path: Path) -> ModuleType:
    spec = spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_example_config_parses() -> None:
    config = load_app_config(ROOT / "config.example.toml")

    assert config.feature.superuser_bypass
    assert config.ai.model == "deepseek-v4-pro"
    assert config.bilibili.polling.windows[0].start == "07:00"
    assert config.message.meeting.commands == ["开播", "会议"]
    assert not config.message.team_audit_welcome.enabled
    assert config.message.team_audit_welcome.feature == "team_audit"
    assert "米米号" in config.message.team_audit_welcome.message
    assert config.seer.team_shortcut.team_ids == []
    assert config.runtime.data_sync.sources["seerapi"].local_path
    assert config.runtime.data_sync.sources["seerapi"].remote_build.enabled
    assert not config.runtime.logging.file_enabled
    assert config.runtime.logging.file_path == "/app/logs/ironsbot.log"
    remote_build_steps = config.runtime.data_sync.sources[
        "seerapi"
    ].remote_build.steps
    assert [step.name for step in remote_build_steps] == [
        "update_unity_config",
        "sync_config_sources",
        "build_seer_data",
        "build_ironsbot_data",
    ]
    assert (
        remote_build_steps[-1].repository
        == "Murmansk5000/seerapi"
    )
    assert (
        remote_build_steps[-1].workflow_id
        == "build-ironsbot-data-db.yml"
    )
    assert config.runtime.help.ignored_plugins == []


def test_dev_and_prod_configs_parse() -> None:
    assert load_app_config(ROOT / "config.dev.toml").feature.group_aliases == {}
    assert not load_app_config(ROOT / "config.prod.toml").runtime.data_sync.on_startup


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

    ai_chat_config = _load_module_from_path(
        "ai_chat_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "ai_chat" / "config.py",
    )
    ai_intent_config = _load_module_from_path(
        "ai_intent_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "ai_intent" / "config.py",
    )
    ai_mention_config = _load_module_from_path(
        "ai_mention_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "ai_mention_guard" / "config.py",
    )
    activity_config = _load_module_from_path(
        "activity_reminder_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "activity" / "config.py",
    )
    bili_config = _load_module_from_path(
        "bilibili_monitor_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "bilibili" / "config.py",
    )
    sendpic_config = _load_module_from_path(
        "sendpic_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "sendpic" / "config.py",
    )
    db_sync_config = _load_module_from_path(
        "db_sync_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "db_sync" / "config.py",
    )
    headless_config = _load_module_from_path(
        "headless_seer_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "headless_seer" / "config.py",
    )
    headless_notice_config = _load_module_from_path(
        "headless_seer_notice_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "headless_seer_notice" / "config.py",
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
    seer_data_config = _load_module_from_path(
        "seer_data_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "seer_data" / "config.py",
    )
    startup_config = _load_module_from_path(
        "startup_notice_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "startup_notice" / "config.py",
    )
    team_shortcut_config = _load_module_from_path(
        "team_shortcut_config_for_app_config_test",
        ROOT / "ironsbot" / "plugins" / "team_shortcut" / "config.py",
    )

    try:
        assert ai_chat_config.get_ai_config().model == "deepseek-v4-pro"
        assert ai_chat_config.get_ai_key() == "sk-test"
        assert ai_intent_config.get_configured_actions()
        assert ai_intent_config.get_team_shortcut_config().commands == ["战队"]
        assert (
            ai_mention_config.get_ai_config().mention_guard_reply_max_per_window
            == DEFAULT_MENTION_GUARD_MAX_PER_WINDOW
        )
        assert activity_config.get_activity_config().lead_hours == [11, 1]
        assert bili_config.get_bili_config().polling.windows[0].start == "07:00"
        assert sendpic_config.get_sendpic_config().local_root.name == "sendpic"
        assert sendpic_config.get_sendpic_cnb_token() == "cnb-token"
        assert "seerapi" in db_sync_config.get_data_sync_config().sources
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
            message_config.get_message_config().reply.max_lines
            == DEFAULT_REPLY_MAX_LINES
        )
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
        assert not scheduled_restart_config.get_restart_config().enabled
        assert "aliases" in seer_data_config.get_data_sync_config().sources
        assert load_app_config(ROOT / "config.example.toml").runtime.priority.enabled
        assert team_shortcut_config.get_team_shortcut_config().commands == ["战队"]
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
            seer_render_cache.get_render_config().cache_max_size_mb
            == DEFAULT_RENDER_CACHE_MAX_SIZE_MB
        )
    finally:
        clear_app_config_cache()
