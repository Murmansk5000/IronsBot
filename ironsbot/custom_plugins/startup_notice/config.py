from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator

from ironsbot.custom_plugins.common.config_utils import nested_json_config


class StartupConfig(BaseModel):
    enabled: bool = True
    message: str = "机器人已开启。"
    delay: float = Field(default=0.0, ge=0)


class Config(BaseModel):
    startup_config: StartupConfig = Field(default_factory=StartupConfig)

    @field_validator("startup_config", mode="before")
    @classmethod
    def normalize_startup_config(cls, value: object) -> object:
        return nested_json_config(value, StartupConfig, name="STARTUP_CONFIG")


plugin_config = get_plugin_config(Config)
