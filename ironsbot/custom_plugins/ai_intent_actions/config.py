from ironsbot.shared.config.config import (
    AiActionBase,
    AiActionTemplate,
    AiIntentAction,
    Config,
    get_shared_config,
    resolve_configured_actions,
)
from ironsbot.shared.config.config import (
    AiConfig as AiIntentConfig,
)

plugin_config = get_shared_config()


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
