from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator

from ironsbot.custom_plugins.common.config_utils import int_list, string_list


class Config(BaseModel):
    team_ids: list[int] = Field(default_factory=list)
    team_commands: list[str] = Field(default_factory=lambda: ["战队"])
    team_resource_users: list[int] = Field(default_factory=list)
    team_resource_message: str = "出来买资源，别逼我求你😡"

    @field_validator("team_ids", "team_resource_users", mode="before")
    @classmethod
    def normalize_int_ids(cls, value: object) -> object:
        return int_list(value)

    @field_validator("team_commands", mode="before")
    @classmethod
    def normalize_commands(cls, value: object) -> object:
        return string_list(value)


plugin_config = get_plugin_config(Config)
