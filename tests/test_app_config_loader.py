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
    assert config.runtime.data_sync.sources["seerapi"].local_path


def test_dev_and_prod_configs_parse() -> None:
    assert load_app_config(ROOT / "config.dev.toml").feature.group_aliases == {}
    assert not load_app_config(ROOT / "config.prod.toml").runtime.data_sync.on_startup


def test_env_secrets_credentials_and_deployment_are_separate() -> None:
    env = {
        "ONEBOT_ACCESS_TOKEN": "token",
        "AI_KEY": "sk-test",
        "SENDPIC_CNB_TOKEN": "cnb-token",
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
    assert credentials.headless_seer_user_id == HEADLESS_USER_ID
    assert deployment.port == DEPLOYMENT_PORT
    assert deployment.command_start == ["/", ""]
    assert deployment.superusers == [SUPERUSER_ID]


def test_small_plugin_config_accessors_read_app_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_app_config_cache()
    monkeypatch.setenv("APP_CONFIG_PATH", str(ROOT / "config.example.toml"))

    meeting_config = _load_module_from_path(
        "meeting_reply_config_for_app_config_test",
        ROOT / "ironsbot" / "custom_plugins" / "meeting_reply" / "config.py",
    )
    server_status_config = _load_module_from_path(
        "server_status_config_for_app_config_test",
        ROOT / "ironsbot" / "custom_plugins" / "server_status" / "config.py",
    )
    startup_config = _load_module_from_path(
        "startup_notice_config_for_app_config_test",
        ROOT / "ironsbot" / "custom_plugins" / "startup_notice" / "config.py",
    )

    try:
        assert meeting_config.get_meeting_config().commands == ["开播", "会议"]
        assert startup_config.get_startup_config().message == "机器人已开启。"
        assert not server_status_config.get_server_status_config().broadcast
    finally:
        clear_app_config_cache()
