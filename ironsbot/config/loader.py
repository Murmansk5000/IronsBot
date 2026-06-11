# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ironsbot.config.models import (
    AppConfig,
    CredentialsConfig,
    DeploymentConfig,
    SecretsConfig,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10 in deployment
    import tomli as tomllib

APP_CONFIG_PATH_ENV = "APP_CONFIG_PATH"
DEFAULT_CONFIG_PATH = Path("config.toml")


def parse_toml_file(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("rb") as file:
        data = tomllib.load(file)
    if not isinstance(data, dict):
        msg = f"config file must contain a TOML table: {config_path}"
        raise TypeError(msg)
    return data


def resolve_app_config_path(
    env: Mapping[str, str] | None = None,
    *,
    default_path: Path = DEFAULT_CONFIG_PATH,
) -> Path | None:
    values = env if env is not None else os.environ
    raw_path = values.get(APP_CONFIG_PATH_ENV, "").strip()
    if raw_path:
        return Path(raw_path)
    if default_path.exists():
        return default_path
    return None


def load_app_config(
    path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> AppConfig:
    resolved_path = Path(path) if path is not None else resolve_app_config_path(env)
    if resolved_path is None:
        return AppConfig()
    return AppConfig.model_validate(parse_toml_file(resolved_path))


@lru_cache(maxsize=1)
def get_app_config(path: str | None = None) -> AppConfig:
    return load_app_config(path)


def clear_app_config_cache() -> None:
    get_app_config.cache_clear()


def _env_data(
    env: Mapping[str, str] | None,
    mapping: Mapping[str, str],
) -> dict[str, str]:
    values = env if env is not None else os.environ
    return {
        field_name: raw_value
        for env_name, field_name in mapping.items()
        if (raw_value := values.get(env_name)) is not None
    }


def load_secrets_config(env: Mapping[str, str] | None = None) -> SecretsConfig:
    return SecretsConfig.model_validate(
        _env_data(
            env,
            {
                "ONEBOT_ACCESS_TOKEN": "onebot_access_token",
                "AI_KEY": "ai_key",
                "SENDPIC_CNB_TOKEN": "sendpic_cnb_token",
            },
        )
    )


def load_credentials_config(
    env: Mapping[str, str] | None = None,
) -> CredentialsConfig:
    return CredentialsConfig.model_validate(
        _env_data(
            env,
            {
                "HEADLESS_SEER_USER_ID": "headless_seer_user_id",
                "HEADLESS_SEER_PASSWORD": "headless_seer_password",
            },
        )
    )


def load_deployment_config(
    env: Mapping[str, str] | None = None,
) -> DeploymentConfig:
    return DeploymentConfig.model_validate(
        _env_data(
            env,
            {
                "ENVIRONMENT": "environment",
                "DRIVER": "driver",
                "HOST": "host",
                "PORT": "port",
                "LOG_LEVEL": "log_level",
                "COMMAND_START": "command_start",
                "SUPERUSERS": "superusers",
                "APP_CONFIG_PATH": "app_config_path",
            },
        )
    )
