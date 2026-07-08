# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

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
CONFIG_EXAMPLE_PATH_ENV = "IRONSBOT_CONFIG_EXAMPLE_PATH"
ENV_EXAMPLE_PATH_ENV = "IRONSBOT_ENV_EXAMPLE_PATH"
DEFAULT_CONFIG_PATH = Path("config/ironsbot.toml")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXAMPLE_CONFIG_PATHS = (
    _PROJECT_ROOT / "config.example.toml",
    Path.cwd() / "config.example.toml",
    Path("/app/config.example.toml"),
)
DEFAULT_ENV_EXAMPLE_PATHS = (
    _PROJECT_ROOT / ".env.example",
    Path.cwd() / ".env.example",
    Path("/app/.env.example"),
)
_LOGGER = logging.getLogger("ironsbot.config")
_EXTRA_FORBIDDEN_ERROR = "extra_forbidden"


def parse_toml_file(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("rb") as file:
        data = tomllib.load(file)
    if not isinstance(data, dict):
        msg = f"config file must contain a TOML table: {config_path}"
        raise TypeError(msg)
    return data


def _format_config_path(location: tuple[object, ...]) -> str:
    parts: list[str] = []
    for item in location:
        if isinstance(item, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{item}]"
            else:
                parts.append(f"[{item}]")
            continue
        parts.append(str(item))
    return ".".join(parts)


def _remove_extra_config_value(data: Any, location: tuple[object, ...]) -> bool:
    if not location:
        return False

    current = data
    for item in location[:-1]:
        if isinstance(item, int):
            if not isinstance(current, list) or item >= len(current):
                return False
            current = current[item]
            continue
        if not isinstance(current, dict) or item not in current:
            return False
        current = current[item]

    final_key = location[-1]
    if not isinstance(final_key, str) or not isinstance(current, dict):
        return False
    if final_key not in current:
        return False

    del current[final_key]
    return True


def _validate_app_config_or_extra_errors(
    data: dict[str, Any],
) -> AppConfig | list[Any]:
    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        errors = exc.errors()
        if not errors or any(
            error.get("type") != _EXTRA_FORBIDDEN_ERROR
            for error in errors
        ):
            raise
        return errors


def _load_app_config_ignoring_extra_fields(data: dict[str, Any]) -> AppConfig:
    ignored_fields: set[str] = set()
    while True:
        validation_result = _validate_app_config_or_extra_errors(data)
        if isinstance(validation_result, AppConfig):
            return validation_result

        removed_any = False
        for error in validation_result:
            location = tuple(error.get("loc", ()))
            if _remove_extra_config_value(data, location):
                ignored_fields.add(_format_config_path(location))
                removed_any = True

        if not removed_any:
            AppConfig.model_validate(data)

        _LOGGER.warning(
            "Ignored unknown app config field(s): "
            + ", ".join(sorted(ignored_fields))
        )


def resolve_app_config_path(
    env: Mapping[str, str] | None = None,
    *,
    default_path: Path = DEFAULT_CONFIG_PATH,
) -> Path:
    values = env if env is not None else os.environ
    raw_path = values.get(APP_CONFIG_PATH_ENV, "").strip()
    if raw_path:
        return Path(raw_path)
    return default_path


def resolve_example_config_path(env: Mapping[str, str] | None = None) -> Path | None:
    values = env if env is not None else os.environ
    raw_path = values.get(CONFIG_EXAMPLE_PATH_ENV, "").strip()
    if raw_path:
        path = Path(raw_path)
        return path if path.exists() else None

    seen: set[Path] = set()
    for path in DEFAULT_EXAMPLE_CONFIG_PATHS:
        normalized = path.resolve() if path.exists() else path.absolute()
        if normalized in seen:
            continue
        seen.add(normalized)
        if path.exists():
            return path
    return None


def _find_existing_path(paths: tuple[Path, ...]) -> Path | None:
    seen: set[Path] = set()
    for path in paths:
        normalized = path.resolve() if path.exists() else path.absolute()
        if normalized in seen:
            continue
        seen.add(normalized)
        if path.exists():
            return path
    return None


def resolve_env_example_path(env: Mapping[str, str] | None = None) -> Path | None:
    values = env if env is not None else os.environ
    raw_path = values.get(ENV_EXAMPLE_PATH_ENV, "").strip()
    if raw_path:
        path = Path(raw_path)
        return path if path.exists() else None
    return _find_existing_path(DEFAULT_ENV_EXAMPLE_PATHS)


def ensure_runtime_env_example_file(
    config_path: str | Path,
    env: Mapping[str, str] | None = None,
) -> bool:
    env_example_path = Path(config_path).parent / "ironsbot.env.example"
    if env_example_path.exists():
        return False

    source_path = resolve_env_example_path(env)
    if source_path is None:
        _LOGGER.warning(
            f"No .env.example was found to create {env_example_path}. "
            "Runtime env files contain secrets and must be created manually."
        )
        return False

    try:
        env_example_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, env_example_path)
    except OSError as exc:
        _LOGGER.warning(
            f"Could not create runtime env example: {env_example_path} "
            f"(source: {source_path}): {exc}"
        )
        return False

    _LOGGER.warning(
        f"Created runtime env example: {env_example_path} (source: {source_path}). "
        "Copy it to ironsbot.env.prod and fill secrets if you use env_file."
    )
    return True


def ensure_app_config_file(
    path: str | Path,
    env: Mapping[str, str] | None = None,
) -> bool:
    config_path = Path(path)
    if config_path.exists():
        return False

    example_path = resolve_example_config_path(env)
    if example_path is None:
        msg = (
            f"app config file does not exist: {config_path}. "
            "No config.example.toml was found to create it automatically. "
            f"Set {APP_CONFIG_PATH_ENV} to an existing TOML file, or copy "
            "config.example.toml manually."
        )
        raise FileNotFoundError(msg)

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example_path, config_path)
    except OSError as exc:
        msg = (
            f"app config file does not exist and could not be created: {config_path}. "
            f"Copy {example_path} to this path manually, or make the config "
            "directory writable for first startup."
        )
        raise RuntimeError(msg) from exc

    _LOGGER.warning(
        f"Created app config from example: {config_path} (source: {example_path}). "
        "Edit this file before production use."
    )
    ensure_runtime_env_example_file(config_path, env)
    return True


def load_app_config(
    path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> AppConfig:
    resolved_path = Path(path) if path is not None else resolve_app_config_path(env)
    ensure_app_config_file(resolved_path, env)
    return _load_app_config_ignoring_extra_fields(parse_toml_file(resolved_path))


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


def _env_field(*parts: str) -> str:
    return "_".join(parts)


def load_secrets_config(env: Mapping[str, str] | None = None) -> SecretsConfig:
    return SecretsConfig.model_validate(
        _env_data(
            env,
            {
                "ONEBOT_ACCESS_TOKEN": _env_field("onebot", "access", "token"),
                "AI_KEY": "ai_key",
                "SENDPIC_CNB_TOKEN": _env_field("sendpic", "cnb", "token"),
                "GITHUB_WORKFLOW_TOKEN": _env_field("github", "workflow", "token"),
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
                "HEADLESS_SEER_PASSWORD": _env_field("headless", "seer", "password"),
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
