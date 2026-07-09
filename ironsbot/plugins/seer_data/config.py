from ironsbot.config.loader import get_app_config
from ironsbot.config.models.runtime import DataSyncConfig


def get_data_sync_config() -> DataSyncConfig:
    return get_app_config().runtime.data_sync

__all__ = [
    "DataSyncConfig",
    "get_data_sync_config",
]
