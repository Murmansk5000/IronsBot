# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
import os
import re
import shutil
import sys
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ironsbot.config.models.app import AppConfig
from ironsbot.config.models.deployment import DeploymentConfig
from ironsbot.config.models.secrets import CredentialsConfig, SecretsConfig
from ironsbot.shared.config.parsing import string_list

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
_MAX_LENIENT_VALIDATION_PASSES = 20
_FEATURE_POLICY_ERROR_RE = re.compile(
    r"feature\.(group_policy|user_policy)\.([^\[]+)\[(\d+)\]=([^,]+)"
)
_BILI_ACCOUNT_ERROR_RE = re.compile(
    r"unknown Bilibili account reference at ([^:]+):\s*(\S+)"
)
_AI_ACTION_ERROR_RE = re.compile(r"ai\.intent_actions\.([^:]+):")


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
    return _validate_app_config_lenient(
        parse_toml_file(resolved_path),
        source_path=resolved_path,
    )


def _validate_app_config_lenient(
    data: dict[str, Any],
    *,
    source_path: Path,
) -> AppConfig:
    candidate = deepcopy(data)

    for _ in range(_MAX_LENIENT_VALIDATION_PASSES):
        config, exc = _try_validate_app_config(candidate)
        if config is not None:
            return config
        if exc is None:
            break

        warnings: list[str] = []
        if not _apply_lenient_config_fixes(candidate, exc, warnings):
            raise exc

        for warning in warnings:
            _LOGGER.warning(
                "Ignoring unrecognized app config entry in %s: %s",
                source_path,
                warning,
            )

    msg = (
        f"app config could not be validated after "
        f"{_MAX_LENIENT_VALIDATION_PASSES} lenient cleanup passes: {source_path}"
    )
    raise RuntimeError(msg)


def _try_validate_app_config(
    data: dict[str, Any],
) -> tuple[AppConfig | None, ValidationError | None]:
    try:
        return AppConfig.model_validate(data), None
    except ValidationError as exc:
        return None, exc


def _apply_lenient_config_fixes(
    data: dict[str, Any],
    exc: ValidationError,
    warnings: list[str],
) -> bool:
    changed = False
    for error in exc.errors():
        error_type = str(error.get("type", ""))
        message = str(error.get("msg", ""))
        loc = tuple(error.get("loc", ()))

        if error_type == "extra_forbidden":
            changed |= _remove_config_path(data, loc, warnings)
            continue

        if "unregistered feature policy key(s)" in message:
            changed |= _remove_unknown_feature_policy_entries(data, message, warnings)
            continue

        if "unknown Bilibili account reference" in message:
            changed |= _remove_unknown_bilibili_account_refs(data, message, warnings)
            continue

        if "unknown AI intent action must configure" in message:
            changed |= _remove_unknown_ai_action(data, message, warnings)
            continue

        if "contains unknown section(s)" in message:
            changed |= _remove_unknown_sections(data, loc, message, warnings)
            continue

    return changed


def _format_config_path(loc: tuple[Any, ...]) -> str:
    parts: list[str] = []
    for part in loc:
        if isinstance(part, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{part}]"
            else:
                parts.append(f"[{part}]")
        else:
            parts.append(str(part))
    return ".".join(parts)


def _parse_config_path(path: str) -> tuple[Any, ...]:
    parts: list[Any] = []
    for segment in path.split("."):
        name = segment
        while "[" in name and name.endswith("]"):
            before, _, after = name.partition("[")
            if before:
                parts.append(before)
            index_text = after[:-1]
            parts.append(int(index_text))
            name = ""
        if name:
            parts.append(name)
    return tuple(parts)


def _resolve_parent(container: Any, loc: tuple[Any, ...]) -> Any:
    current = container
    for part in loc:
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                return None
            current = current[part]
            continue
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _remove_config_path(
    data: dict[str, Any],
    loc: tuple[Any, ...],
    warnings: list[str],
) -> bool:
    if not loc:
        return False

    parent = _resolve_parent(data, loc[:-1])
    key = loc[-1]
    path = _format_config_path(loc)

    if isinstance(parent, dict) and isinstance(key, str) and key in parent:
        parent.pop(key, None)
        warnings.append(f"{path} is not a recognized field")
        return True

    if isinstance(parent, list) and isinstance(key, int) and 0 <= key < len(parent):
        parent.pop(key)
        warnings.append(f"{path} is not a recognized list item")
        return True

    return False


def _remove_unknown_feature_policy_entries(
    data: dict[str, Any],
    message: str,
    warnings: list[str],
) -> bool:
    feature_config = data.get("feature")
    if not isinstance(feature_config, dict):
        return False

    removals: list[tuple[str, str, int, str]] = [
        (policy_name, target, int(index), feature.strip())
        for policy_name, target, index, feature in _FEATURE_POLICY_ERROR_RE.findall(
            message
        )
    ]
    changed = False
    for policy_name, target, index, feature in sorted(
        removals,
        key=lambda item: (item[0], item[1], item[2]),
        reverse=True,
    ):
        policy = feature_config.get(policy_name)
        if not isinstance(policy, dict):
            continue
        values = policy.get(target)
        if not isinstance(values, list):
            continue

        entry_changed = False
        if 0 <= index < len(values) and str(values[index]).strip() == feature:
            values.pop(index)
            entry_changed = True
        else:
            original_len = len(values)
            values[:] = [item for item in values if str(item).strip() != feature]
            entry_changed = len(values) != original_len

        if entry_changed:
            changed = True
            warnings.append(
                f"feature.{policy_name}.{target} contains unknown feature "
                f"{feature!r}"
            )
    return changed


def _remove_unknown_bilibili_account_refs(
    data: dict[str, Any],
    message: str,
    warnings: list[str],
) -> bool:
    changed = False
    for path, account in _BILI_ACCOUNT_ERROR_RE.findall(message):
        loc = _parse_config_path(path)
        if _remove_config_path(data, loc, warnings):
            warnings[-1] = f"{path} references unknown Bilibili account {account!r}"
            changed = True
    return changed


def _remove_unknown_ai_action(
    data: dict[str, Any],
    message: str,
    warnings: list[str],
) -> bool:
    ai_config = data.get("ai")
    if not isinstance(ai_config, dict):
        return False
    actions = ai_config.get("intent_actions")
    if not isinstance(actions, dict):
        return False

    changed = False
    for action_id in _AI_ACTION_ERROR_RE.findall(message):
        if action_id in actions:
            actions.pop(action_id, None)
            warnings.append(
                f"ai.intent_actions.{action_id} is incomplete and was ignored"
            )
            changed = True
    return changed


def _remove_unknown_sections(
    data: dict[str, Any],
    loc: tuple[Any, ...],
    message: str,
    warnings: list[str],
) -> bool:
    if not loc:
        return False

    _, _, raw_unknown = message.partition("section(s):")
    unknown_sections = {
        section.strip().lower()
        for section in raw_unknown.split(",")
        if section.strip()
    }
    if not unknown_sections:
        return False

    parent = _resolve_parent(data, loc[:-1])
    key = loc[-1]
    if not isinstance(parent, dict) or not isinstance(key, str) or key not in parent:
        return False

    current_value = parent[key]
    current_sections = string_list(current_value)
    filtered = [
        section
        for section in current_sections
        if str(section).strip().lower() not in unknown_sections
    ]
    if len(filtered) == len(current_sections):
        return False

    path = _format_config_path(loc)
    if filtered:
        parent[key] = filtered
    else:
        parent.pop(key, None)
    warnings.append(
        f"{path} contains unknown section(s) "
        f"{', '.join(sorted(unknown_sections))}"
    )
    return True


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
