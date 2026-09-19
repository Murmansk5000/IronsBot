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

from ironsbot.config.loader import load_settings
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
    parser.add_argument(
        "--provider",
        help="Provider alias to test; defaults to the first configured provider.",
    )
    parser.add_argument(
        "--model",
        help="Model to test; defaults to the provider's first model.",
    )
    args = parser.parse_args()

    env = _merged_env(REPO_ROOT / args.env)
    config = load_settings(env=env).ai
    providers = dict(config.configured_providers)
    provider_name = args.provider or next(iter(providers), "")
    provider = providers.get(provider_name)
    if provider is None:
        _write_lines(["AI API 测试失败", "没有找到已配置密钥的 AI 提供商。"])
        return 1
    model = args.model or provider.models[0]
    if model not in provider.models:
        _write_lines(
            [
                "AI API 测试失败",
                f"模型 {model} 未在 ai.providers.{provider_name}.models 中声明。",
            ]
        )
        return 1
    settings = AiApiSettings(
        api_key=provider.api_key,
        base_url=provider.base_url,
        model=model,
        timeout=config.timeout,
        thinking=provider.thinking,
    )
    result = await check_ai_api(settings)
    status = result.status_code if result.status_code is not None else "未知"

    if result.ok:
        _write_lines(
            [
                "AI API 测试成功",
                f"提供商：{provider_name}",
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
            f"提供商：{provider_name}",
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
