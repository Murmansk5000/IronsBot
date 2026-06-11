# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

from ironsbot.shared.config.parsing import int_list, string_list

ENABLED_COMMANDS_REQUIRED_ERROR = "已启用的指令消息动作必须配置 commands"
DEFAULT_SENDPIC_MESSAGE_TEMPLATE = "{image}"
SendpicBackendType: TypeAlias = Literal["cnb", "local"]


def _default_sendpic_local_root() -> Path:
    return Path("sendpic")


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


class MeetingConfig(BaseModel):
    number: str = ""
    template: str = (
        "腾讯会议\n"
        "腾讯会议号：{meeting_number}\n"
        "点击链接直接加入：{meeting_url}"
    )
    commands: list[str] = Field(default_factory=lambda: ["开播", "会议"])

    @field_validator("commands", mode="before")
    @classmethod
    def normalize_commands(cls, value: object) -> object:
        return string_list(value)


class PicConfig(BaseModel):
    id: str
    backend: SendpicBackendType
    command: str
    aliases: set[str] = Field(default_factory=set)
    image_dir: str
    image_filename_template: str
    help_message: str | None = None
    message_template: str = DEFAULT_SENDPIC_MESSAGE_TEMPLATE

    @field_validator("id", "command", "image_dir", "image_filename_template")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("aliases", mode="before")
    @classmethod
    def normalize_aliases(cls, value: object) -> object:
        return string_list(value)


class SendpicBehaviorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cnb_repo: str | None = None
    local_root: Path = Path("sendpic")
    configs: list[PicConfig] = Field(default_factory=list)
    enabled_ids: frozenset[str] = Field(default_factory=frozenset)

    @field_validator("enabled_ids", mode="before")
    @classmethod
    def normalize_enabled_ids(cls, value: object) -> object:
        return string_list(value)


class SendpicConfig(SendpicBehaviorConfig):
    cnb_token: str | None = None
    local_root: Path = Field(default_factory=_default_sendpic_local_root)

    @field_validator("configs")
    @classmethod
    def validate_pics(cls, value: list[PicConfig]) -> list[PicConfig]:
        seen: set[str] = set()
        for pic in value:
            if pic.id in seen:
                raise ValueError(f"图片类型【{pic.id}】重复")
            seen.add(pic.id)

        return value

    @model_validator(mode="after")
    def validate_configs(self) -> Self:
        for pic in self.configs:
            if pic.backend == "cnb" and (not self.cnb_token or not self.cnb_repo):
                raise ValueError(  # noqa: TRY003
                    f"CNB 相关配置未设置，而命令【{pic.command}】需要该配置"
                )
        return self


class MessageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: ReplyLineConfig = Field(default_factory=ReplyLineConfig)
    private_commands: list[PrivateCommandMessageAction] = Field(default_factory=list)
    private_schedules: list[PrivateScheduledMessageAction] = Field(
        default_factory=list
    )
    group_commands: list[GroupCommandMessageAction] = Field(default_factory=list)
    group_schedules: list[GroupScheduledMessageAction] = Field(default_factory=list)
    meeting: MeetingConfig = Field(default_factory=MeetingConfig)
    sendpic: SendpicBehaviorConfig = Field(default_factory=SendpicBehaviorConfig)


__all__ = ["MessageConfig", "SendpicBehaviorConfig"]
