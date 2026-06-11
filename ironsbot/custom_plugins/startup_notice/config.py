from ironsbot.config import get_app_config
from ironsbot.shared.config.config import StartupConfig


def get_startup_config() -> StartupConfig:
    return get_app_config().runtime.startup_notice

__all__ = [
    "StartupConfig",
    "get_startup_config",
]
