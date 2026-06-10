from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator

from ironsbot.custom_plugins.common.config_utils import (
    nested_json_config,
    string_list,
)


class MeetingConfig(BaseModel):
    number: str = ""
    template: str = (
        "\u817e\u8baf\u4f1a\u8bae\n"
        "\u817e\u8baf\u4f1a\u8bae\u53f7\uff1a{meeting_number}\n"
        "\u70b9\u51fb\u94fe\u63a5\u76f4\u63a5\u52a0\u5165\uff1a"
        "{meeting_url}"
    )
    commands: list[str] = Field(
        default_factory=lambda: [
            "\u5f00\u64ad",
            "\u4f1a\u8bae",
        ]
    )

    @field_validator("commands", mode="before")
    @classmethod
    def normalize_commands(cls, value: object) -> object:
        return string_list(value)


class Config(BaseModel):
    meeting_config: MeetingConfig = Field(default_factory=MeetingConfig)

    @field_validator("meeting_config", mode="before")
    @classmethod
    def normalize_meeting_config(cls, value: object) -> object:
        return nested_json_config(value, MeetingConfig, name="MEETING_CONFIG")


plugin_config = get_plugin_config(Config)
