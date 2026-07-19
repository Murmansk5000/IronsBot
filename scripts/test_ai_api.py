# SPDX-License-Identifier: MIT
"""Run a local AI API health check without exposing a bot command.

Usage:
    uv run python scripts/test_ai_api.py
    uv run python scripts/test_ai_api.py --env .env.prod
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ironsbot.core.commands import json_object
from ironsbot.integrations.http.ai import (
    AiApiSettings,
    check_ai_api,
)

DEFAULT_ENV_FILE = ".env.dev"
QUOTE_PAIR_MIN_LENGTH = 2


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if (
        len(value) >= QUOTE_PAIR_MIN_LENGTH
        and value[0] == value[-1]
        and value[0] in {'"', "'"}
    ):
        return value[1:-1]
    return value


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = _strip_env_value(raw_value)

    return values


def _json_env(env: dict[str, str], key: str) -> dict:
    raw_value = env.get(key, "").strip()
    if not raw_value:
        return {}

    try:
        return json_object(raw_value, name=key)
    except (TypeError, ValueError):
        return {}


def _float_config(config: dict, key: str, default: float) -> float:
    try:
        return float(config.get(key) or default)
    except (TypeError, ValueError):
        return default


def _bool_config(config: dict, key: str, *, default: bool = False) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _build_settings(env: dict[str, str]) -> AiApiSettings:
    ai_config = _json_env(env, "AI_CONFIG")
    return AiApiSettings(
        api_key=env.get("IRONSBOT_AI_KEY", ""),
        base_url=str(ai_config.get("base_url") or "https://api.deepseek.com"),
        model=str(ai_config.get("model") or "deepseek-v4-pro"),
        timeout=_float_config(ai_config, "timeout", 45.0),
        thinking=_bool_config(ai_config, "thinking"),
    )


def _merged_env(env_file: Path) -> dict[str, str]:
    values = _load_env_file(env_file)
    values.update(os.environ)
    return values


def _write_lines(lines: list[str]) -> None:
    sys.stdout.write("\n".join(lines) + "\n")


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Test the configured AI API.")
    parser.add_argument(
        "--env",
        default=DEFAULT_ENV_FILE,
        help="Environment file to load before reading process env.",
    )
    args = parser.parse_args()

    settings = _build_settings(_merged_env(REPO_ROOT / args.env))
    result = await check_ai_api(settings)
    status = result.status_code if result.status_code is not None else "未知"

    if result.ok:
        _write_lines(
            [
                "AI API 测试成功",
                f"接口：{settings.base_url.rstrip('/')}",
                f"模型：{settings.model}",
                f"HTTP：{status}",
                f"耗时：{result.elapsed_ms} ms",
                f"回复：{result.reply[:80]}",
            ]
        )
        return 0

    _write_lines(
        [
            "AI API 测试失败",
            f"接口：{settings.base_url.rstrip('/')}",
            f"模型：{settings.model}",
            f"HTTP：{status}",
            f"耗时：{result.elapsed_ms} ms",
            f"错误：{result.error}",
        ]
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
