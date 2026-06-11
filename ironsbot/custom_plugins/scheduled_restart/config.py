from ironsbot.shared.config.config import (
    INVALID_RESTART_TIME_ERROR,
    Config,
    RestartConfig,
    get_shared_config,
)

plugin_config = get_shared_config()

__all__ = [
    "INVALID_RESTART_TIME_ERROR",
    "Config",
    "RestartConfig",
    "plugin_config",
]
