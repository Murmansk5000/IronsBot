from ironsbot.shared.config.config import (
    AiConfig as AiChatConfig,
)
from ironsbot.shared.config.config import Config, get_shared_config

plugin_config = get_shared_config()

__all__ = [
    "AiChatConfig",
    "Config",
    "plugin_config",
]
