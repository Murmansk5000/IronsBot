from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Self


class BaseMessageAction(BaseModel):
    id: str = ""
    enabled: bool = True
    message: str

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("消息内容不能为空")
        return message


class CommandMessageAction(BaseMessageAction):
    commands: list[str] = Field(default_factory=list)

    @field_validator("commands")
    @classmethod
    def normalize_commands(cls, value: list[str]) -> list[str]:
        commands: list[str] = []
        for command in value:
            command = command.strip()
            if command and command not in commands:
                commands.append(command)
        return commands

    @model_validator(mode="after")
    def validate_enabled_command_action(self) -> Self:
        if self.enabled and not self.commands:
            raise ValueError("已启用的指令消息动作必须配置 commands")
        return self


class ScheduledMessageAction(BaseMessageAction):
    hour: int = Field(ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    day_of_week: str | None = None


class PrivateCommandMessageAction(CommandMessageAction):
    allowed_user_ids: list[int] = Field(default_factory=list)


class PrivateScheduledMessageAction(ScheduledMessageAction):
    user_ids: list[int] = Field(default_factory=list)


class GroupCommandMessageAction(CommandMessageAction):
    group_ids: list[int] = Field(default_factory=list)
    at_user_ids: list[int] = Field(default_factory=list)


class GroupScheduledMessageAction(ScheduledMessageAction):
    group_ids: list[int] = Field(default_factory=list)
    at_user_ids: list[int] = Field(default_factory=list)


class Config(BaseModel):
    msg_at_trigger: bool = False
    msg_private_commands: list[PrivateCommandMessageAction] = Field(
        default_factory=list
    )
    msg_private_schedules: list[PrivateScheduledMessageAction] = Field(
        default_factory=list
    )
    msg_group_commands: list[GroupCommandMessageAction] = Field(
        default_factory=list
    )
    msg_group_schedules: list[GroupScheduledMessageAction] = Field(
        default_factory=list
    )


plugin_config = get_plugin_config(Config)
