# SPDX-License-Identifier: MIT
from nonebot import get_driver

from ironsbot.config.loader import get_app_config, load_secrets_config
from ironsbot.config.models.ai import AiConfig


def get_ai_config() -> AiConfig:
    return get_app_config().ai


def get_ai_key() -> str:
    key = load_secrets_config().ai_key.strip()
    if key:
        return key

    try:
        return str(getattr(get_driver().config, "ai_key", "") or "").strip()
    except ValueError:
        return ""


__all__ = [
    "AiConfig",
    "get_ai_config",
    "get_ai_key",
]
