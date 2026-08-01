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
_HEADLESS_WORKER_ENV_PREFIXES = {
    "HEADLESS_SEER_USER_ID": "user_id",
    "HEADLESS_SEER_PASSWORD": "password",
}


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


class HeadlessWorkerEnvironmentError(ValueError):
    @classmethod
    def duplicate(
        cls,
        worker_key: str,
        key: str,
        first_name: str,
        second_name: str,
    ) -> HeadlessWorkerEnvironmentError:
        return cls(
            f"duplicate headless worker {worker_key} {key} variables: "
            f"{first_name} and {second_name}"
        )

    @classmethod
    def configured_in_toml(cls) -> HeadlessWorkerEnvironmentError:
        return cls(
            "operations.headless_workers is managed from suffixed "
            "HEADLESS_SEER_* environment variables"
        )

    @classmethod
    def missing_pair(
        cls,
        worker_key: str,
        missing_names: str,
    ) -> HeadlessWorkerEnvironmentError:
        return cls(
            f"headless worker {worker_key} is missing environment values: "
            f"{missing_names}"
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


def _headless_worker_env_entry(env_name: str) -> tuple[str, str] | None:
    """Return a normalized worker key and field for a suffixed env variable."""

    for prefix, field in _HEADLESS_WORKER_ENV_PREFIXES.items():
        if env_name == prefix or not env_name.startswith(prefix):
            continue
        worker_key = env_name.removeprefix(prefix).lstrip("_").upper()
        if worker_key:
            return worker_key, field
    return None


def _inject_headless_workers(
    data: dict[str, Any],
    *,
    env: Mapping[str, str],
) -> None:
    """Load any named headless account pairs from the process environment.

    The unnumbered pair is always worker 1 and is handled by ``_SECRET_ENV_PATHS``.
    Extra pairs use the same arbitrary suffix on both values, for example
    ``HEADLESS_SEER_USER_ID_RANK_A`` and ``HEADLESS_SEER_PASSWORD_RANK_A``.
    A direct suffix without an underscore is also accepted for Docker UIs that
    prefer it. Duplicates are rejected rather than guessed.
    """

    values: dict[str, dict[str, str]] = {}
    sources: dict[tuple[str, str], str] = {}
    for env_name, value in env.items():
        entry = _headless_worker_env_entry(env_name)
        if entry is None:
            continue
        worker_key, key = entry
        source_key = (worker_key, key)
        if source_key in sources:
            raise HeadlessWorkerEnvironmentError.duplicate(
                worker_key,
                key,
                sources[source_key],
                env_name,
            )
        values.setdefault(worker_key, {})[key] = value
        sources[source_key] = env_name

    if not values:
        return

    operations = data.setdefault("operations", {})
    if not isinstance(operations, dict):
        msg = "configuration table operations must be a TOML table"
        raise TypeError(msg)
    if "headless_workers" in operations:
        raise HeadlessWorkerEnvironmentError.configured_in_toml()

    workers: list[dict[str, Any]] = []
    for worker_key, worker in sorted(values.items()):
        missing = {"user_id", "password"}.difference(worker)
        if missing:
            missing_names = ", ".join(sorted(missing))
            raise HeadlessWorkerEnvironmentError.missing_pair(
                worker_key,
                missing_names,
            )
        workers.append({"worker_key": worker_key, **worker})
    operations["headless_workers"] = workers


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
    _inject_headless_workers(data, env=values)
    unknown_paths = _unknown_field_paths(data)
    settings = Settings.model_validate(data, extra="ignore")
    _report_ignored_unknown_fields(unknown_paths)
    return settings
