# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

from ironsbot.shared.config.parsing import int_list, string_list

ENABLED_COMMANDS_REQUIRED_ERROR = "已启用的指令消息动作必须配置 commands"
DEFAULT_SENDPIC_MESSAGE_TEMPLATE = "{image}"
TEAM_AUDIT_WELCOME_MESSAGE_REQUIRED_ERROR = (
    "team_audit_welcome.message must not be empty"
)
OUTBOUND_RATE_LIMIT_MESSAGE_REQUIRED_ERROR = (
    "outbound_rate_limit.cooldown_message must not be empty"
)
PUSH_UNSUBSCRIBE_REQUIRED_ERROR = (
    "push_unsubscribe requires non-empty commands and restore_commands"
)
SendpicBackendType: TypeAlias = Literal["cnb", "local"]


def _default_sendpic_local_root() -> Path:
    return Path("sendpic")


class BaseMessageAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    name: str = ""
    enabled: bool = True
    feature: str = "text"
    message: str

    @field_validator("id", "name")
    @classmethod
    def normalize_optional_text(cls, value: str) -> str:
        return value.strip()

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


class OutboundRateLimitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    window_seconds: float = Field(default=60.0, gt=0)
    max_messages: int = Field(default=10, ge=1)
    cooldown_message: str = (
        "本群消息发送过于频繁，机器人进入冷却时间，请稍后再试。"
    )

    @field_validator("cooldown_message")
    @classmethod
    def validate_cooldown_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError(OUTBOUND_RATE_LIMIT_MESSAGE_REQUIRED_ERROR)
        return message


class PushUnsubscribeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commands: list[str] = Field(default_factory=lambda: ["td", "退订"])
    restore_commands: list[str] = Field(
        default_factory=lambda: ["订阅", "恢复订阅"]
    )
    data_path: str = "data/messaging/push_unsubscriptions.sqlite"
    hint: str = "回复 TD 可管理推送订阅。"
    group_hint: str = "群主/管理员发送 TD 或 订阅可管理本群推送订阅。"

    @field_validator("commands", "restore_commands", mode="before")
    @classmethod
    def normalize_commands(cls, value: object) -> object:
        return string_list(value)

    @field_validator("data_path", "hint", "group_hint")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError(PUSH_UNSUBSCRIBE_REQUIRED_ERROR)
        return text

    @model_validator(mode="after")
    def validate_commands(self) -> Self:
        if not self.commands or not self.restore_commands:
            raise ValueError(PUSH_UNSUBSCRIBE_REQUIRED_ERROR)
        return self


class RedPacketNoticeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    cooldown_seconds: float = Field(default=60.0, ge=0)


class MeetingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

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


class TeamAuditWelcomeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    feature: str = "team_audit"
    groups: list[int | str] = Field(default_factory=list)
    message: str = (
        "欢迎加入战队审核群。\n"
        "如果想加入战队，请先发送“米米号+你的米米号”查询个人信息，"
        "方便管理员审核。\n"
        "审核通过后，管理员会指引你加入主群和战队；入队完成后请退出审核群。\n"
        "如果已经加入主群，或者不想加入战队，请退出本审核群。"
    )
    followup_enabled: bool = True
    followup_after_hours: float = Field(default=24.0, gt=0)
    followup_message: str = (
        "你加入战队审核群已经 {hours:g} 小时了，还没有发送审核信息。\n"
        "如果想加入战队，请发送“米米号+你的米米号”供管理员审核；"
        "如果已经加入主群，或者不想加入战队，请退出本审核群。"
    )
    followup_cache_path: str = "data/team_audit_welcome/pending.sqlite"

    @field_validator("feature")
    @classmethod
    def normalize_feature(cls, value: str) -> str:
        feature = value.strip()
        return feature or "team_audit"

    @field_validator("groups", mode="before")
    @classmethod
    def normalize_groups(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            stripped = value.strip()
            return string_list(stripped) if stripped else []
        return value

    @field_validator("message", "followup_message", "followup_cache_path")
    @classmethod
    def validate_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError(TEAM_AUDIT_WELCOME_MESSAGE_REQUIRED_ERROR)
        return message


class PicConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

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

    outbound_rate_limit: OutboundRateLimitConfig = Field(
        default_factory=OutboundRateLimitConfig
    )
    push_unsubscribe: PushUnsubscribeConfig = Field(
        default_factory=PushUnsubscribeConfig
    )
    red_packet_notice: RedPacketNoticeConfig = Field(
        default_factory=RedPacketNoticeConfig
    )
    private_commands: list[PrivateCommandMessageAction] = Field(default_factory=list)
    private_schedules: list[PrivateScheduledMessageAction] = Field(
        default_factory=list
    )
    group_commands: list[GroupCommandMessageAction] = Field(default_factory=list)
    group_schedules: list[GroupScheduledMessageAction] = Field(default_factory=list)
    meeting: MeetingConfig = Field(default_factory=MeetingConfig)
    team_audit_welcome: TeamAuditWelcomeConfig = Field(
        default_factory=TeamAuditWelcomeConfig
    )
    sendpic: SendpicBehaviorConfig = Field(default_factory=SendpicBehaviorConfig)


__all__ = [
    "MessageConfig",
    "PushUnsubscribeConfig",
    "RedPacketNoticeConfig",
    "SendpicBehaviorConfig",
]
