# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ironsbot.config.models.settings import Settings

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10 in deployment
    import tomli as tomllib

TOMLDecodeError = tomllib.TOMLDecodeError

CONFIG_ENV = "APP_CONFIG_PATH"
DEFAULT_CONFIG_PATH = Path("config/ironsbot.toml")
LUCKY_SKIN_WINDOW_PASSWORD_ENV_PREFIX = "LUCKY_WINDOW_SEER_PASSWORD_"
_MIN_SEER_PLAYER_ID = 10001
_SECRET_ENV_PATHS = (
    ("ONEBOT_ACCESS_TOKEN", ("bot", "onebot_token")),
    ("AI_KEY", ("ai", "api_key")),
    ("HEADLESS_SEER_USER_ID", ("operations", "headless", "user_id")),
    ("HEADLESS_SEER_PASSWORD", ("operations", "headless", "password")),
    ("SENDPIC_CNB_TOKEN", ("messaging", "sendpic", "cnb_token")),
    ("GITHUB_WORKFLOW_TOKEN", ("operations", "data_sync", "github_token")),
    (
        "DOCKER_REGISTRY_USERNAME",
        ("operations", "docker_update", "registry_username"),
    ),
    (
        "DOCKER_REGISTRY_TOKEN",
        ("operations", "docker_update", "registry_token"),
    ),
)
class ConfigFileNotFoundError(FileNotFoundError):
    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(
            "未找到 IronsBot 配置文件："
            f"{path}\n"
            "请创建该文件（可参考 config.example.toml），并通过 "
            f"{CONFIG_ENV} 指向它。Docker/Unraid 默认路径为 "
            "/config/ironsbot.toml。"
        )


def _inject_secret(
    data: dict[str, Any],
    *,
    env_name: str,
    path: Sequence[str],
    env: Mapping[str, str],
) -> None:
    table = data
    for part in path[:-1]:
        child = table.setdefault(part, {})
        if not isinstance(child, dict):
            msg = (
                f"configuration table {'.'.join(path[:-1])} "
                "must be a TOML table"
            )
            raise TypeError(msg)
        table = child

    field = path[-1]
    if field in table:
        msg = f"{'.'.join(path)} is secret and must be set with {env_name}"
        raise ValueError(msg)
    if (value := env.get(env_name)) is not None:
        table[field] = value


def _inject_referenced_credentials(
    entries: object,
    *,
    path: str,
    id_field: str,
    id_env_field: str,
    env: Mapping[str, str],
) -> None:
    if not isinstance(entries, list):
        return
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        entry_path = f"{path}[{index}]"
        for field in (id_field, "password"):
            if field in entry:
                env_field = id_env_field if field == id_field else "password_env"
                message = (
                    f"{entry_path}.{field} is secret and must be set through "
                    f"the entry's {env_field} reference"
                )
                raise ValueError(message)
        entry[id_field] = _referenced_secret(
            entry,
            env_field=id_env_field,
            path=entry_path,
            env=env,
        )
        entry["password"] = _referenced_secret(
            entry,
            env_field="password_env",
            path=entry_path,
            env=env,
        )


def _inject_headless_worker_secrets(
    data: dict[str, Any],
    *,
    env: Mapping[str, str],
) -> None:
    operations = data.get("operations")
    if not isinstance(operations, dict):
        return
    headless = operations.get("headless")
    if not isinstance(headless, dict):
        return
    _inject_referenced_credentials(
        headless.get("workers", []),
        path="operations.headless.workers",
        id_field="user_id",
        id_env_field="user_id_env",
        env=env,
    )


def _inject_lucky_skin_window_secrets(
    data: dict[str, Any],
    *,
    env: Mapping[str, str],
) -> None:
    seer = data.get("seer")
    if not isinstance(seer, dict):
        return
    lucky_skin_window = seer.get("lucky_skin_window")
    if not isinstance(lucky_skin_window, dict):
        return
    entries = lucky_skin_window.get("accounts", [])
    if not isinstance(entries, list):
        return
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        path = f"seer.lucky_skin_window.accounts[{index}]"
        if "password" in entry:
            message = f"{path}.password is secret and must use its environment variable"
            raise ValueError(message)
        player_id = _configured_lucky_skin_window_player_id(entry)
        if player_id is None:
            continue
        entry["password"] = _environment_secret(
            f"{LUCKY_SKIN_WINDOW_PASSWORD_ENV_PREFIX}{player_id}",
            path=f"{path}.password",
            env=env,
        )


def _configured_lucky_skin_window_player_id(entry: dict[str, Any]) -> int | None:
    value = entry.get("player_id")
    if value is None:
        return None
    try:
        player_id = int(value)
    except (TypeError, ValueError):
        return None
    return player_id if player_id >= _MIN_SEER_PLAYER_ID else None


def _referenced_secret(
    entry: dict[str, Any],
    *,
    env_field: str,
    path: str,
    env: Mapping[str, str],
) -> str:
    env_name = str(entry.get(env_field) or "").strip()
    if not env_name:
        message = f"{path}.{env_field} must not be empty"
        raise ValueError(message)
    return _environment_secret(env_name, path=f"{path}.{env_field}", env=env)


def _environment_secret(
    env_name: str,
    *,
    path: str,
    env: Mapping[str, str],
) -> str:
    value = env.get(env_name)
    if value is None or not str(value).strip():
        message = (
            f"{path} references missing environment variable {env_name}"
        )
        raise ValueError(message)
    return str(value)


def _format_config_path(location: tuple[str | int, ...]) -> str:
    result = ""
    for part in location:
        if isinstance(part, int):
            result += f"[{part}]"
        elif result:
            result += f".{part}"
        else:
            result = part
    return result


def _unknown_field_paths(data: dict[str, Any]) -> tuple[str, ...]:
    """Collect strict-model extra-field diagnostics before ignoring them."""

    try:
        Settings.model_validate(data)
    except ValidationError as exc:
        paths = [
            _format_config_path(error["loc"])
            for error in exc.errors()
            if error["type"] == "extra_forbidden"
        ]
        return tuple(dict.fromkeys(paths))
    return ()


def _report_ignored_unknown_fields(paths: tuple[str, ...]) -> None:
    if not paths:
        return
    details = "\n".join(f"- {path}" for path in paths)
    sys.stderr.write(
        "IronsBot 配置含无法识别的字段，已忽略并继续启动：\n"
        f"{details}\n"
    )


def load_settings(
    path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Settings:
    values = env if env is not None else os.environ
    resolved_path = Path(
        path
        if path is not None
        else values.get(CONFIG_ENV, DEFAULT_CONFIG_PATH)
    )
    if not resolved_path.exists():
        raise ConfigFileNotFoundError(resolved_path)
    with resolved_path.open("rb") as file:
        data = tomllib.load(file)

    for env_name, field_path in _SECRET_ENV_PATHS:
        _inject_secret(
            data,
            env_name=env_name,
            path=field_path,
            env=values,
        )
    _inject_headless_worker_secrets(data, env=values)
    _inject_lucky_skin_window_secrets(data, env=values)
    unknown_paths = _unknown_field_paths(data)
    settings = Settings.model_validate(data, extra="ignore")
    _report_ignored_unknown_fields(unknown_paths)
    return settings
