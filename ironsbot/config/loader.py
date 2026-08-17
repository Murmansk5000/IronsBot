# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ironsbot.config.models.ai import AI_ENDPOINT_NAME_PATTERN
from ironsbot.config.models.settings import Settings
from ironsbot.core.commands import normalize_command_text
from ironsbot.core.seer_ids import is_valid_player_id

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10 in deployment
    import tomli as tomllib

TOMLDecodeError = tomllib.TOMLDecodeError

CONFIG_ENV = "APP_CONFIG_PATH"
DEFAULT_CONFIG_PATH = Path("config/ironsbot.toml")
SEER_PASSWORD_ENV_PREFIX = "SEER_PASSWORD_"
AI_ENDPOINT_KEY_SECRET_ERROR = (
    "ai.endpoints[{index}].api_key is secret and must be set with "
    "AI_KEY_<ENDPOINT_NAME>"
)
_SECRET_ENV_PATHS = (
    ("ONEBOT_ACCESS_TOKEN", ("bot", "onebot_token")),
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


def _inject_player_account_passwords(  # noqa: C901, PLR0912
    data: dict[str, Any],
    *,
    env: Mapping[str, str],
) -> None:
    seer = data.get("seer")
    if not isinstance(seer, dict):
        return
    entries = seer.get("player_accounts", [])
    if not isinstance(entries, list):
        return

    accounts_by_reference: dict[str, tuple[int, dict[str, Any], str]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        path = f"seer.player_accounts[{index}]"
        if "password" in entry:
            message = (
                f"{path}.password is secret and must be set with "
                f"{SEER_PASSWORD_ENV_PREFIX}<player_id>"
            )
            raise ValueError(message)
        player_id = _configured_player_id(entry)
        if player_id is None:
            continue
        accounts_by_reference[str(player_id)] = (player_id, entry, path)
        for field in ("name", "aliases"):
            raw_values = (
                (entry.get(field),)
                if field == "name"
                else entry.get(field, [])
            )
            if not isinstance(raw_values, (list, tuple)):
                continue
            for raw_value in raw_values:
                value = normalize_command_text(str(raw_value))
                if value:
                    accounts_by_reference[value] = (player_id, entry, path)

    required: dict[int, tuple[dict[str, Any], str]] = {}
    operations = data.get("operations")
    headless = operations.get("headless") if isinstance(operations, dict) else None
    headless_accounts = (
        headless.get("accounts", []) if isinstance(headless, dict) else []
    )
    if isinstance(headless_accounts, list):
        for index, raw_reference in enumerate(headless_accounts):
            reference = normalize_command_text(str(raw_reference).strip())
            account = accounts_by_reference.get(reference)
            if account is not None:
                player_id, entry, _account_path = account
                required[player_id] = (
                    entry,
                    f"operations.headless.accounts[{index}]",
                )

    lucky_skin_window = seer.get("lucky_skin_window")
    if isinstance(lucky_skin_window, dict):
        subscriptions = lucky_skin_window.get("accounts", [])
        if isinstance(subscriptions, list):
            for index, subscription in enumerate(subscriptions):
                if not isinstance(subscription, dict):
                    continue
                path = f"seer.lucky_skin_window.accounts[{index}]"
                if "password" in subscription:
                    raise ValueError(  # noqa: TRY003
                        f"{path}.password is secret and is not a supported field"
                    )
                if lucky_skin_window.get("enabled") is not True:
                    continue
                raw_reference = subscription.get("account")
                normalized = normalize_command_text(str(raw_reference or ""))
                account = accounts_by_reference.get(normalized)
                if account is not None:
                    player_id, entry, account_path = account
                    required[player_id] = (entry, account_path)

    for player_id, (entry, path) in required.items():
        entry["password"] = _normalize_player_password(
            _environment_secret(
                f"{SEER_PASSWORD_ENV_PREFIX}{player_id}",
                path=f"{path}.password",
                env=env,
            )
        )


def _inject_ai_endpoint_keys(
    data: dict[str, Any],
    *,
    env: Mapping[str, str],
) -> None:
    ai = data.get("ai")
    if not isinstance(ai, dict):
        return
    endpoints = ai.get("endpoints", [])
    if not isinstance(endpoints, list):
        return

    for index, endpoint in enumerate(endpoints):
        if not isinstance(endpoint, dict):
            continue
        if "api_key" in endpoint:
            raise ValueError(AI_ENDPOINT_KEY_SECRET_ERROR.format(index=index))
        raw_name = endpoint.get("name")
        name = str(raw_name or "").strip()
        if not AI_ENDPOINT_NAME_PATTERN.fullmatch(name):
            continue
        env_name = f"AI_KEY_{name.upper()}"
        if (value := env.get(env_name)) is not None:
            endpoint["api_key"] = value


def _normalize_player_password(value: str) -> str:
    """Return the credential format expected by the legacy Seer login API."""
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()


def _configured_player_id(entry: dict[str, Any]) -> int | None:
    value = entry.get("player_id")
    if value is None:
        return None
    try:
        player_id = int(value)
    except (TypeError, ValueError):
        return None
    return player_id if is_valid_player_id(player_id) else None


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
    _inject_ai_endpoint_keys(data, env=values)
    _inject_player_account_passwords(data, env=values)
    unknown_paths = _unknown_field_paths(data)
    settings = Settings.model_validate(data, extra="ignore")
    _report_ignored_unknown_fields(unknown_paths)
    return settings
