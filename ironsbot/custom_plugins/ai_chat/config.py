from nonebot import get_plugin_config

from ironsbot.custom_plugins.common.ai_config import (
    AiConfig as AiChatConfig,
)
from ironsbot.custom_plugins.common.ai_config import (
    Config,
)

plugin_config = get_plugin_config(Config)

__all__ = [
    "AiChatConfig",
    "Config",
    "plugin_config",
]
