# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomllib
from pydantic import ValidationError

from ironsbot.config.models.settings import Settings
from ironsbot.core.commands import normalize_command_text
from ironsbot.core.seer_ids import is_valid_player_id

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

TOMLDecodeError = tomllib.TOMLDecodeError
logger = logging.getLogger(__name__)

CONFIG_ENV = "APP_CONFIG_PATH"
DEFAULT_CONFIG_PATH = Path("config/ironsbot.toml")
SEER_PASSWORD_ENV_PREFIX = "SEER_PASSWORD_"
QQ_OFFICIAL_SECRET_ENV_PREFIX = "APP_SECRET_"
_RETIRED_QQ_OFFICIAL_ENV_PREFIXES = (
    "QQ_OFFICIAL_APP_ID_",
    "QQ_OFFICIAL_SECRET_",
)
ONEBOT_TRUSTED_OFFICIAL_BOT_ENV_PREFIX = "ONEBOT_TRUSTED_OFFICIAL_BOT_"
AI_KEY_ENV_PREFIX = "AI_KEY_"
LEGACY_AI_KEY_ERROR = (
    "AI_KEY is retired; use AI_KEY_<PROVIDER> for a provider declared under "
    "ai.providers"
)
AI_PROVIDER_ENV_COLLISION_ERROR = "AI provider aliases collide as environment names"
_ONEBOT_ENV_PATHS = (
    ("ONEBOT_ENABLED", ("bot", "onebot", "enabled")),
    ("ONEBOT_SEND_MESSAGES", ("bot", "onebot", "send_messages")),
    (
        "ONEBOT_IDENTITY_VERIFICATION",
        ("bot", "onebot", "identity_verification"),
    ),
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


def _inject_ai_provider_credentials(
    data: dict[str, Any],
    *,
    env: Mapping[str, str],
) -> None:
    legacy_key = str(env.get("AI_KEY", "")).strip()
    if legacy_key:
        raise ValueError(LEGACY_AI_KEY_ERROR)

    ai = data.get("ai")
    providers = ai.get("providers") if isinstance(ai, dict) else None
    if not isinstance(providers, dict):
        providers = {}

    declared_names = {str(name).upper(): str(name) for name in providers}
    if len(declared_names) != len(providers):
        raise ValueError(AI_PROVIDER_ENV_COLLISION_ERROR)
    for alias, provider in providers.items():
        if isinstance(provider, dict) and "api_key" in provider:
            environment_name = str(alias).upper()
            raise ValueError(  # noqa: TRY003
                f"ai.providers.{alias}.api_key is a deployment credential and "
                f"must be set with {AI_KEY_ENV_PREFIX}{environment_name}"
            )

    environment_names = {
        key[len(AI_KEY_ENV_PREFIX) :].upper()
        for key, value in env.items()
        if key.startswith(AI_KEY_ENV_PREFIX) and str(value).strip()
    }
    unknown_names = sorted(environment_names - declared_names.keys())
    if unknown_names:
        raise ValueError(
            "AI environment keys reference undeclared providers: "
            + ", ".join(unknown_names)
        )

    for environment_name in environment_names:
        alias = declared_names[environment_name]
        provider = providers[alias]
        if not isinstance(provider, dict):
            continue
        provider["api_key"] = str(env[AI_KEY_ENV_PREFIX + environment_name]).strip()


def _inject_qq_official_credentials(
    data: dict[str, Any],
    *,
    env: Mapping[str, str],
) -> None:
    retired = sorted(
        key
        for key, value in env.items()
        if any(key.startswith(prefix) for prefix in _RETIRED_QQ_OFFICIAL_ENV_PREFIXES)
        and str(value).strip()
    )
    if retired:
        raise ValueError(
            "retired QQ Official credential variables are not supported; "
            "declare app_id in TOML and use APP_SECRET_<AppID>: " + ", ".join(retired)
        )
    bot = data.get("bot")
    qq_official = bot.get("qq_official") if isinstance(bot, dict) else None
    accounts = qq_official.get("accounts") if isinstance(qq_official, dict) else None
    if not isinstance(accounts, dict):
        accounts = {}
    declared_app_ids = {
        str(account.get("app_id", "")).strip(): str(name)
        for name, account in accounts.items()
        if isinstance(account, dict) and str(account.get("app_id", "")).strip()
    }
    credential_app_ids = {
        key[len(QQ_OFFICIAL_SECRET_ENV_PREFIX) :]
        for key, value in env.items()
        if key.startswith(QQ_OFFICIAL_SECRET_ENV_PREFIX) and str(value).strip()
    }
    unknown_app_ids = sorted(credential_app_ids - declared_app_ids.keys())
    if unknown_app_ids:
        app_ids = ", ".join(unknown_app_ids)
        msg = (
            "QQ Official Secret environment variables reference undeclared AppIDs: "
            f"{app_ids}"
        )
        raise ValueError(msg)
    for raw_name, raw_account in accounts.items():
        if not isinstance(raw_account, dict):
            continue
        name = str(raw_name)
        if "secret" in raw_account:
            app_id = str(raw_account.get("app_id", "")).strip()
            env_name = QQ_OFFICIAL_SECRET_ENV_PREFIX + app_id
            msg = (
                f"bot.qq_official.accounts.{name}.secret is a deployment credential "
                f"and must be set with {env_name}"
            )
            raise ValueError(msg)
        app_id = str(raw_account.get("app_id", "")).strip()
        if not app_id:
            msg = f"bot.qq_official.accounts.{name}.app_id is required"
            raise ValueError(msg)
        env_name = QQ_OFFICIAL_SECRET_ENV_PREFIX + app_id
        if secret := str(env.get(env_name, "")).strip():
            raw_account["secret"] = secret


def _inject_onebot_deployment_settings(
    data: dict[str, Any],
    *,
    env: Mapping[str, str],
) -> None:
    for env_name, path in _ONEBOT_ENV_PATHS:
        if (value := env.get(env_name)) is not None:
            _set_environment_override(data, path=path, value=value)

    bot = data.setdefault("bot", {})
    if not isinstance(bot, dict):
        msg = "configuration table bot must be a TOML table"
        raise TypeError(msg)
    onebot = bot.setdefault("onebot", {})
    if not isinstance(onebot, dict):
        msg = "configuration table bot.onebot must be a TOML table"
        raise TypeError(msg)
    trusted = onebot.setdefault("trusted_official_bots", {})
    if not isinstance(trusted, dict):
        msg = (
            "configuration table bot.onebot.trusted_official_bots must be a TOML table"
        )
        raise TypeError(msg)

    accounts = (
        bot.get("qq_official", {}).get("accounts", {})
        if isinstance(bot.get("qq_official"), dict)
        else {}
    )
    declared_names = (
        {str(name).upper(): str(name) for name in accounts}
        if isinstance(accounts, dict)
        else {}
    )
    environment_names = {
        key[len(ONEBOT_TRUSTED_OFFICIAL_BOT_ENV_PREFIX) :].upper()
        for key, value in env.items()
        if key.startswith(ONEBOT_TRUSTED_OFFICIAL_BOT_ENV_PREFIX) and str(value).strip()
    }
    unknown_names = sorted(environment_names - declared_names.keys())
    if unknown_names:
        raise ValueError(
            "trusted OneBot official bot IDs reference undeclared accounts: "
            + ", ".join(unknown_names)
        )
    for environment_name in environment_names:
        alias = declared_names[environment_name]
        trusted[alias] = env[ONEBOT_TRUSTED_OFFICIAL_BOT_ENV_PREFIX + environment_name]


def _set_environment_override(
    data: dict[str, Any],
    *,
    path: Sequence[str],
    value: str,
) -> None:
    table = data
    for part in path[:-1]:
        child = table.setdefault(part, {})
        if not isinstance(child, dict):
            msg = f"configuration table {'.'.join(path[:-1])} must be a TOML table"
            raise TypeError(msg)
        table = child
    table[path[-1]] = value


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
            msg = f"configuration table {'.'.join(path[:-1])} must be a TOML table"
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
                (entry.get(field),) if field == "name" else entry.get(field, [])
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
        message = f"{path} references missing environment variable {env_name}"
        raise ValueError(message)
    return str(value)


def load_settings(
    path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Settings:
    values = env if env is not None else os.environ
    resolved_path = Path(
        path if path is not None else values.get(CONFIG_ENV, DEFAULT_CONFIG_PATH)
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
    _inject_ai_provider_credentials(data, env=values)
    _inject_onebot_deployment_settings(data, env=values)
    _inject_qq_official_credentials(data, env=values)
    _inject_player_account_passwords(data, env=values)
    return _validate_settings(data)


def _validate_settings(data: dict[str, Any]) -> Settings:
    """Ignore unknown TOML fields visibly while keeping known fields strict."""

    try:
        return Settings.model_validate(data)
    except ValidationError as error:
        unknown_paths = tuple(
            _format_config_path(item["loc"])
            for item in error.errors()
            if item["type"] == "extra_forbidden"
        )
        if not unknown_paths:
            raise

    logger.warning(
        "已忽略不会生效的未知配置字段：%s。请核对拼写或从 TOML 删除旧字段。",
        ", ".join(unknown_paths),
    )
    return Settings.model_validate(data, extra="ignore")


def _format_config_path(location: Sequence[str | int]) -> str:
    result = ""
    for part in location:
        if isinstance(part, int):
            result += f"[{part}]"
        elif result:
            result += f".{part}"
        else:
            result = part
    return result
