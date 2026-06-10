# SPDX-License-Identifier: MIT
from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator

from ironsbot.custom_plugins.common.config_utils import nested_json_config

DEFAULT_BROADCAST_MESSAGE = "赛尔号已经开服了。"


class ServerStatusConfig(BaseModel):
    broadcast: bool = False
    broadcast_message: str = DEFAULT_BROADCAST_MESSAGE
    broadcast_cooldown_minutes: int = Field(default=1440, ge=0)

    @field_validator("broadcast_message")
    @classmethod
    def normalize_broadcast_message(cls, value: str) -> str:
        message = value.strip()
        return message or DEFAULT_BROADCAST_MESSAGE


class Config(BaseModel):
    server_status_config: ServerStatusConfig = Field(default_factory=ServerStatusConfig)

    @field_validator("server_status_config", mode="before")
    @classmethod
    def normalize_server_status_config(cls, value: object) -> object:
        return nested_json_config(
            value,
            ServerStatusConfig,
            name="SERVER_STATUS_CONFIG",
        )


plugin_config = get_plugin_config(Config)
