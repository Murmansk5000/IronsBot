from ironsbot.config import AppConfig, get_app_config
from ironsbot.config.models.runtime import DataSyncConfig

Config = AppConfig


def get_data_sync_config() -> DataSyncConfig:
    return get_app_config().runtime.data_sync

__all__ = [
    "Config",
    "DataSyncConfig",
    "get_data_sync_config",
]
