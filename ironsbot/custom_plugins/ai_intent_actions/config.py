from ironsbot.config import AppConfig, get_app_config
from ironsbot.config.models.ai import (
    AiActionBase,
    AiActionTemplate,
    AiIntentAction,
)
from ironsbot.config.models.ai import (
    AiConfig as AiIntentConfig,
)
from ironsbot.services.ai.client import get_ai_key
from ironsbot.services.ai.intent import (
    get_configured_actions,
    get_team_ids,
    get_team_resource_users,
    get_team_shortcut_config,
)

Config = AppConfig


def get_ai_config() -> AiIntentConfig:
    return get_app_config().ai


__all__ = [
    "AiActionBase",
    "AiActionTemplate",
    "AiIntentAction",
    "AiIntentConfig",
    "Config",
    "get_ai_config",
    "get_ai_key",
    "get_configured_actions",
    "get_team_ids",
    "get_team_resource_users",
    "get_team_shortcut_config",
]
