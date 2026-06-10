from pathlib import Path

from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Self

from ironsbot.custom_plugins.common.config_utils import (
    int_list,
    nested_json_config,
    string_list,
)

ENABLED_COMMANDS_REQUIRED_ERROR = "已启用的指令消息动作必须配置 commands"


class BaseMessageAction(BaseModel):
    id: str = ""
    enabled: bool = True
    feature: str = "text"
    message: str

    @field_validator("feature")
    @classmethod
    def normalize_feature(cls, value: str) -> str:
        feature = value.strip()
        return feature or "text"

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("消息内容不能为空")
        return message


class CommandMessageAction(BaseMessageAction):
    commands: list[str] = Field(default_factory=list)

    @field_validator("commands", mode="before")
    @classmethod
    def normalize_commands(cls, value: object) -> object:
        return string_list(value)

    @model_validator(mode="after")
    def validate_enabled_command_action(self) -> Self:
        if self.enabled and not self.commands:
            raise ValueError(ENABLED_COMMANDS_REQUIRED_ERROR)
        return self


class ScheduledMessageAction(BaseMessageAction):
    hour: int = Field(ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    day_of_week: str | None = None


class PrivateCommandMessageAction(CommandMessageAction):
    pass


class PrivateScheduledMessageAction(ScheduledMessageAction):
    feature: str = "text_push"


class GroupCommandMessageAction(CommandMessageAction):
    at_user_ids: list[int] = Field(default_factory=list)

    @field_validator("at_user_ids", mode="before")
    @classmethod
    def normalize_at_user_ids(cls, value: object) -> object:
        return int_list(value)


class GroupScheduledMessageAction(ScheduledMessageAction):
    feature: str = "text_push"
    at_user_ids: list[int] = Field(default_factory=list)

    @field_validator("at_user_ids", mode="before")
    @classmethod
    def normalize_at_user_ids(cls, value: object) -> object:
        return int_list(value)


class ReplyLineConfig(BaseModel):
    default_lines: int = Field(default=-1, ge=-1)
    min_lines: int = Field(default=5, ge=1)
    max_lines: int = Field(default=80, ge=1)
    limit_path: Path = Path("data/message_actions/reply_limits.sqlite")

    @model_validator(mode="after")
    def validate_line_range(self) -> Self:
        if self.min_lines > self.max_lines:
            msg = "reply.min_lines must be less than or equal to reply.max_lines"
            raise ValueError(msg)
        return self


class MessageActionsConfig(BaseModel):
    reply: ReplyLineConfig = Field(default_factory=ReplyLineConfig)
    private_commands: list[PrivateCommandMessageAction] = Field(default_factory=list)
    private_schedules: list[PrivateScheduledMessageAction] = Field(
        default_factory=list
    )
    group_commands: list[GroupCommandMessageAction] = Field(default_factory=list)
    group_schedules: list[GroupScheduledMessageAction] = Field(default_factory=list)


class Config(BaseModel):
    msg_config: MessageActionsConfig = Field(default_factory=MessageActionsConfig)

    @field_validator("msg_config", mode="before")
    @classmethod
    def normalize_msg_config(cls, value: object) -> object:
        return nested_json_config(value, MessageActionsConfig, name="MSG_CONFIG")


plugin_config = get_plugin_config(Config)
