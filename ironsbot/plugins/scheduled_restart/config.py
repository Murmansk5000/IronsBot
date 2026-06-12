from ironsbot.config import AppConfig, get_app_config
from ironsbot.config.models.runtime import (
    INVALID_RESTART_TIME_ERROR,
    RestartConfig,
)

Config = AppConfig


def get_restart_config() -> RestartConfig:
    return get_app_config().runtime.restart

__all__ = [
    "INVALID_RESTART_TIME_ERROR",
    "Config",
    "RestartConfig",
    "get_restart_config",
]
