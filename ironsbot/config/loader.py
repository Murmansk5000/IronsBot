# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ironsbot.config.models.settings import Settings

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10 in deployment
    import tomli as tomllib

CONFIG_ENV = "APP_CONFIG_PATH"
DEFAULT_CONFIG_PATH = Path("config/ironsbot.toml")
_SECRET_ENV_PATHS = (
    ("ONEBOT_ACCESS_TOKEN", ("bot", "onebot_token")),
    ("AI_KEY", ("ai", "api_key")),
    ("HEADLESS_SEER_USER_ID", ("operations", "headless", "user_id")),
    ("HEADLESS_SEER_PASSWORD", ("operations", "headless", "password")),
    ("SENDPIC_CNB_TOKEN", ("messaging", "sendpic", "cnb_token")),
    ("GITHUB_WORKFLOW_TOKEN", ("operations", "data_sync", "github_token")),
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
    with resolved_path.open("rb") as file:
        data = tomllib.load(file)

    for env_name, field_path in _SECRET_ENV_PATHS:
        _inject_secret(
            data,
            env_name=env_name,
            path=field_path,
            env=values,
        )
    return Settings.model_validate(data)
