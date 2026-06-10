from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator

from ironsbot.custom_plugins.common.config_utils import (
    int_list,
    nested_json_config,
    string_list,
)


class TeamConfig(BaseModel):
    commands: list[str] = Field(default_factory=lambda: ["\u6218\u961f"])
    resource_threshold: int = Field(default=1000, ge=0)
    query_timeout_seconds: int = Field(default=20, gt=0)
    resource_message: str = (
        "\u51fa\u6765\u4e70\u8d44\u6e90\uff0c"
        "\u522b\u903c\u6211\u6c42\u4f60\U0001f621"
    )

    @field_validator("commands", mode="before")
    @classmethod
    def normalize_commands(cls, value: object) -> object:
        return string_list(value)


class Config(BaseModel):
    team_ids: list[int] = Field(default_factory=list)
    team_resource_users: list[int] = Field(default_factory=list)
    team_config: TeamConfig = Field(default_factory=TeamConfig)

    @field_validator("team_ids", "team_resource_users", mode="before")
    @classmethod
    def normalize_int_ids(cls, value: object) -> object:
        return int_list(value)

    @field_validator("team_config", mode="before")
    @classmethod
    def normalize_team_config(cls, value: object) -> object:
        return nested_json_config(value, TeamConfig, name="TEAM_CONFIG")


plugin_config = get_plugin_config(Config)
