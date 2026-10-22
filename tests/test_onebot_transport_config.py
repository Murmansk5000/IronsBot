from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from ironsbot.config.loader import load_settings
from ironsbot.config.models.transport import OneBotConfig

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_TIMEOUT = 30.0
TOML_TIMEOUT = 9.0
ENV_TIMEOUT = 7.5
CONFIG = """
[bot.onebot]
api_timeout = 9.0
ws_urls = ["ws://toml.example/onebot"]
api_roots = { "1" = "https://toml.example/api" }
nicknames = ["toml nickname"]
"""


def test_onebot_transport_defaults_preserve_the_existing_contract() -> None:
    config = OneBotConfig()
    assert config.api_timeout == DEFAULT_TIMEOUT
    assert not config.ws_urls and not config.api_roots and not config.nicknames
    assert not config.http_secret
    assert OneBotConfig(api_timeout=None).api_timeout is None


def test_onebot_toml_and_canonical_environment_overrides(tmp_path: Path) -> None:
    path = tmp_path / "onebot.toml"
    path.write_text(CONFIG, encoding="utf-8")
    configured = load_settings(path, env={}).bot.onebot
    assert configured.api_timeout == TOML_TIMEOUT
    assert {str(url) for url in configured.ws_urls} == {"ws://toml.example/onebot"}
    assert str(configured.api_roots["1"]) == "https://toml.example/api"
    assert configured.nicknames == {"toml nickname"}

    settings = load_settings(
        path,
        env={
            "ONEBOT_WS_URLS": '["wss://env.example/onebot"]',
            "ONEBOT_API_ROOTS": '{"2":"http://env.example/api"}',
            "NICKNAME": '["env nickname"]',
            "API_TIMEOUT": str(ENV_TIMEOUT),
            "ONEBOT_SECRET": "synthetic-signing-secret",
            "ONEBOT_ACCESS_TOKEN": "synthetic-access-token",
        },
    )
    config = settings.bot.onebot
    assert config.api_timeout == ENV_TIMEOUT
    assert {str(url) for url in config.ws_urls} == {"wss://env.example/onebot"}
    assert {key: str(value) for key, value in config.api_roots.items()} == {
        "2": "http://env.example/api"
    }
    assert config.nicknames == {"env nickname"}
    assert config.http_secret == "synthetic-signing-secret"
    assert settings.bot.onebot_token == "synthetic-access-token"
    assert "synthetic-signing-secret" not in repr(config)
    assert "http_secret" not in config.model_dump()


@pytest.mark.parametrize("name", ["ONEBOT_WS_URLS", "ONEBOT_API_ROOTS", "NICKNAME"])
def test_malformed_transport_json_reports_only_the_variable(
    tmp_path: Path, name: str
) -> None:
    path = tmp_path / "onebot.toml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match=f"{name} must contain valid JSON") as captured:
        load_settings(path, env={name: "malformed-private-test-value"})
    assert "malformed-private-test-value" not in str(captured.value)


@pytest.mark.parametrize(
    "name,value",
    [
        ("ONEBOT_WS_URLS", "{}"),
        ("ONEBOT_API_ROOTS", "[]"),
        ("NICKNAME", '"not-an-array"'),
    ],
)
def test_transport_environment_shapes_are_validated(
    tmp_path: Path, name: str, value: str
) -> None:
    path = tmp_path / "onebot.toml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(path, env={name: value})


@pytest.mark.parametrize(
    "values",
    [
        {"ws_urls": ["https://example.invalid/"]},
        {"api_roots": {"1": "ws://example.invalid/"}},
        {"api_roots": {"alias": "http://example.invalid/"}},
        {"api_roots": {"0": "http://example.invalid/"}},
        {"nicknames": [" "]},
        {"api_timeout": 0},
        {"api_timeout": -1},
        {"api_timeout": float("inf")},
        {"api_timeout": float("nan")},
    ],
)
def test_invalid_transport_fields_fail(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        OneBotConfig.model_validate(values)


def test_http_signature_secret_cannot_be_written_in_toml(tmp_path: Path) -> None:
    path = tmp_path / "onebot.toml"
    path.write_text(
        '[bot.onebot]\nhttp_secret = "test-not-a-real-secret"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="must be set with ONEBOT_SECRET") as captured:
        load_settings(path, env={"ONEBOT_SECRET": "env-not-a-real-secret"})
    assert "test-not-a-real-secret" not in str(captured.value)
    assert "env-not-a-real-secret" not in str(captured.value)


@pytest.mark.parametrize(
    "name",
    [
        "ONEBOT_V11_ACCESS_TOKEN",
        "ONEBOT_V11_SECRET",
        "ONEBOT_V11_WS_URLS",
        "ONEBOT_V11_API_ROOTS",
    ],
)
def test_retired_sdk_environment_aliases_cannot_silently_disable_authentication(
    tmp_path: Path, name: str
) -> None:
    path = tmp_path / "onebot.toml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="retired OneBot variables") as captured:
        load_settings(path, env={name: "private-test-value"})
    assert name in str(captured.value)
    assert "private-test-value" not in str(captured.value)


def test_onebot_config_and_loader_do_not_import_the_framework(tmp_path: Path) -> None:
    path = tmp_path / "onebot.toml"
    path.write_text(CONFIG, encoding="utf-8")
    script = """
import sys
sys.modules['nonebot'] = None
from ironsbot.config.loader import load_settings
settings = load_settings(sys.argv[1], env={'ONEBOT_SECRET': 'synthetic-secret'})
assert settings.bot.onebot.api_timeout == 9.0
assert settings.bot.onebot.http_secret == 'synthetic-secret'
assert not any(name.startswith('nonebot.') for name in sys.modules)
print('OWN_ONEBOT_CONFIG_OK')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "OWN_ONEBOT_CONFIG_OK"
