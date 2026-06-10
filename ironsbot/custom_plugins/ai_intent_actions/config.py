from nonebot import get_plugin_config

from ironsbot.custom_plugins.common.ai_config import (
    AiActionBase,
    AiActionTemplate,
    AiIntentAction,
    Config,
    resolve_configured_actions,
)
from ironsbot.custom_plugins.common.ai_config import (
    AiConfig as AiIntentConfig,
)

plugin_config = get_plugin_config(Config)


def get_configured_actions() -> list[AiIntentAction]:
    return resolve_configured_actions(plugin_config.ai_config)


__all__ = [
    "AiActionBase",
    "AiActionTemplate",
    "AiIntentAction",
    "AiIntentConfig",
    "Config",
    "get_configured_actions",
    "plugin_config",
]
