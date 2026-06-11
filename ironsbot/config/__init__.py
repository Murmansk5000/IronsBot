# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

_EXPORTS = {
    "APP_CONFIG_PATH_ENV": ("ironsbot.config.loader", "APP_CONFIG_PATH_ENV"),
    "AppConfig": ("ironsbot.config.models", "AppConfig"),
    "CredentialsConfig": ("ironsbot.config.models", "CredentialsConfig"),
    "DEFAULT_CONFIG_PATH": ("ironsbot.config.loader", "DEFAULT_CONFIG_PATH"),
    "DeploymentConfig": ("ironsbot.config.models", "DeploymentConfig"),
    "SecretsConfig": ("ironsbot.config.models", "SecretsConfig"),
    "clear_app_config_cache": ("ironsbot.config.loader", "clear_app_config_cache"),
    "get_app_config": ("ironsbot.config.loader", "get_app_config"),
    "load_app_config": ("ironsbot.config.loader", "load_app_config"),
    "load_credentials_config": ("ironsbot.config.loader", "load_credentials_config"),
    "load_deployment_config": ("ironsbot.config.loader", "load_deployment_config"),
    "load_secrets_config": ("ironsbot.config.loader", "load_secrets_config"),
    "parse_toml_file": ("ironsbot.config.loader", "parse_toml_file"),
    "resolve_app_config_path": ("ironsbot.config.loader", "resolve_app_config_path"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)

    module_name, attr_name = _EXPORTS[name]
    module = __import__(module_name, fromlist=[attr_name])
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)
