from ironsbot.config.loader import get_app_config
from ironsbot.config.models.ai import (
    AiActionBase,
    AiIntentAction,
)
from ironsbot.config.models.ai import (
    AiConfig as AiIntentConfig,
)
from ironsbot.services.ai.client import get_ai_key
from ironsbot.services.ai.intent import (
    get_configured_actions,
    get_team_resource_config,
)


def get_ai_config() -> AiIntentConfig:
    return get_app_config().ai


__all__ = [
    "AiActionBase",
    "AiIntentAction",
    "AiIntentConfig",
    "get_ai_config",
    "get_ai_key",
    "get_configured_actions",
    "get_team_resource_config",
]
