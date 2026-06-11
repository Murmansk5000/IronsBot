from nonebot import get_driver

from ironsbot.config import AppConfig, get_app_config, load_secrets_config
from ironsbot.shared.config.config import (
    AiConfig as AiChatConfig,
)

Config = AppConfig


def get_ai_config() -> AiChatConfig:
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
    "AiChatConfig",
    "Config",
    "get_ai_config",
    "get_ai_key",
]
