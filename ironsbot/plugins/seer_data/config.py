from ironsbot.shared.config.config import Config, DataSyncConfig, get_shared_config

plugin_config = get_shared_config()

__all__ = [
    "Config",
    "DataSyncConfig",
    "plugin_config",
]
