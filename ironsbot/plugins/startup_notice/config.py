from ironsbot.config.loader import get_app_config
from ironsbot.config.models.runtime import StartupConfig


def get_startup_config() -> StartupConfig:
    return get_app_config().runtime.startup_notice

__all__ = [
    "StartupConfig",
    "get_startup_config",
]
