from ironsbot.shared.config.config import Config, TeamConfig, get_shared_config

plugin_config = get_shared_config()

__all__ = [
    "Config",
    "TeamConfig",
    "plugin_config",
]
