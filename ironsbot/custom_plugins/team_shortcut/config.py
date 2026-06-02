from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator


class Config(BaseModel):
    team_shortcut_group_ids: list[int] = Field(default_factory=list)
    team_shortcut_team_ids: list[int] = Field(default_factory=list)
    team_shortcut_commands: list[str] = Field(default_factory=lambda: ["战队"])
    team_shortcut_resource_notice_user_ids: list[int] = Field(default_factory=list)
    team_shortcut_resource_notice_message: str = "出来买资源，别逼我求你😡"

    @field_validator("team_shortcut_commands")
    @classmethod
    def normalize_commands(cls, value: list[str]) -> list[str]:
        commands: list[str] = []
        for command in value:
            command = command.strip()
            if command and command not in commands:
                commands.append(command)
        return commands


plugin_config = get_plugin_config(Config)
