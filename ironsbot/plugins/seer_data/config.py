from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator

from ironsbot.custom_plugins.common.config_utils import nested_json_config
from ironsbot.custom_plugins.common.data_sync_config import DataSyncConfig


class Config(BaseModel):
    data_sync_config: DataSyncConfig = Field(default_factory=DataSyncConfig)

    @field_validator("data_sync_config", mode="before")
    @classmethod
    def normalize_data_sync_config(cls, value: object) -> object:
        return nested_json_config(value, DataSyncConfig, name="DATA_SYNC_CONFIG")


plugin_config = get_plugin_config(Config)
