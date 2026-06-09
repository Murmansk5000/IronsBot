import json

from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator


class Config(BaseModel):
    team_ids: list[int] = Field(default_factory=list)
    team_commands: list[str] = Field(default_factory=lambda: ["战队"])
    team_resource_users: list[int] = Field(default_factory=list)
    team_resource_message: str = "出来买资源，别逼我求你😡"

    @field_validator("team_resource_users", mode="before")
    @classmethod
    def normalize_resource_notice_user_ids(cls, value: object) -> object:
        if value is None or value == "":
            return []

        if isinstance(value, int):
            return [value]

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []

            if text.startswith("["):
                return json.loads(text)

            return [
                int(item.strip())
                for item in text.split(",")
                if item.strip()
            ]

        return value

    @field_validator("team_commands")
    @classmethod
    def normalize_commands(cls, value: list[str]) -> list[str]:
        commands: list[str] = []
        for raw_command in value:
            command = raw_command.strip()
            if command and command not in commands:
                commands.append(command)
        return commands


plugin_config = get_plugin_config(Config)
