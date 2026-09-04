# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from string import Formatter

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

from ironsbot.core.commands import (  # noqa: TC001 - Pydantic resolves aliases
    NormalizedStringList,
)
from ironsbot.core.messaging import SendpicBehaviorConfig
from ironsbot.core.onebot_references import (  # noqa: TC001 - Pydantic resolves aliases
    OneBotReferenceList,
)
from ironsbot.core.time import normalize_daily_time

ENABLED_COMMANDS_REQUIRED_ERROR = "已启用的指令消息动作必须配置 commands"
ENABLED_KEYWORDS_REQUIRED_ERROR = "已启用的关键词回复动作必须配置 keywords"
ENABLED_MENTION_USERS_REQUIRED_ERROR = "已启用的 AT 专属回复必须配置 user_ids"
COMMAND_ID_REQUIRED_ERROR = "command message action requires a non-empty id"
COMMAND_ID_FORMAT_ERROR = (
    "command message action id may only contain letters, numbers, dots, "
    "underscores, and hyphens"
)
TEAM_AUDIT_WELCOME_MESSAGE_REQUIRED_ERROR = (
    "team_audit_welcome.message must not be empty"
)
TEAM_AUDIT_FINAL_FOLLOWUP_AFTER_HOURS_ERROR = (
    "team_audit_welcome.final_followup_after_hours "
    "must be greater than followup_after_hours"
)
OUTBOUND_RATE_LIMIT_MESSAGE_REQUIRED_ERROR = (
    "outbound_rate_limit.cooldown_message must not be empty"
)
OUTBOUND_RATE_LIMIT_WINDOWS_REQUIRED_ERROR = (
    "outbound_rate_limit.windows must not be empty"
)
OUTBOUND_RATE_LIMIT_WINDOWS_DUPLICATE_ERROR = (
    "outbound_rate_limit.windows contains duplicate window_seconds"
)
PUSH_UNSUBSCRIBE_REQUIRED_ERROR = (
    "push_unsubscribe requires non-empty commands and restore_commands"
)
PUSH_DELIVERY_DELAY_RANGE_ERROR = (
    "messaging.push_delivery.batch_delay_max_seconds must be greater than or equal "
    "to batch_delay_min_seconds"
)
SCHEDULE_ID_REQUIRED_ERROR = "定时推送必须配置非空 id"
SCHEDULE_ID_FORMAT_ERROR = "定时推送 id 只能包含英文字母、数字、点、下划线和连字符"
SCHEDULE_ID_DUPLICATE_ERROR = "定时推送 id 必须全局唯一"
SCHEDULE_TIME_ERROR = "messaging.schedules.time must use HH:MM:SS"
_SCHEDULE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
BotReference = str | int
COMMAND_COOLDOWN_MESSAGE_REQUIRED_ERROR = (
    "messaging.command_cooldown.cooldown_message must not be empty"
)
COMMAND_COOLDOWN_MESSAGE_FORMAT_ERROR = (
    "messaging.command_cooldown.cooldown_message only supports {remaining_seconds}"
)
COMMAND_COOLDOWN_IN_PROGRESS_REQUIRED_ERROR = (
    "messaging.command_cooldown.in_progress_message must not be empty"
)
COMMAND_COOLDOWN_DUPLICATE_REQUIRED_ERROR = (
    "messaging.command_cooldown.duplicate_message must not be empty"
)
COMMAND_COOLDOWN_WINDOWS_REQUIRED_ERROR = (
    "messaging.command_cooldown.windows must not be empty"
)
COMMAND_COOLDOWN_WINDOWS_DUPLICATE_ERROR = (
    "messaging.command_cooldown.windows contains duplicate window_seconds"
)
COMMAND_COOLDOWN_EMPTY_ID_ERROR = (
    "messaging.command_cooldown.commands contains an empty command id"
)


class DuplicateScheduleIdError(ValueError):
    @classmethod
    def from_ids(cls, schedule_ids: set[str]) -> DuplicateScheduleIdError:
        duplicate_text = ", ".join(sorted(schedule_ids))
        return cls(f"{SCHEDULE_ID_DUPLICATE_ERROR}: {duplicate_text}")


class CommandCooldownWindowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_seconds: float = Field(gt=0)
    max_requests: int = Field(ge=1)


def _default_command_cooldown_windows() -> list[CommandCooldownWindowConfig]:
    return [
        CommandCooldownWindowConfig(window_seconds=60.0, max_requests=3),
        CommandCooldownWindowConfig(window_seconds=300.0, max_requests=5),
    ]


def _normalize_command_cooldown_windows(
    windows: list[CommandCooldownWindowConfig],
    *,
    required: bool,
) -> list[CommandCooldownWindowConfig]:
    if not windows:
        if required:
            raise ValueError(COMMAND_COOLDOWN_WINDOWS_REQUIRED_ERROR)
        return []
    seen: set[float] = set()
    for window in windows:
        if window.window_seconds in seen:
            raise ValueError(COMMAND_COOLDOWN_WINDOWS_DUPLICATE_ERROR)
        seen.add(window.window_seconds)
    return sorted(windows, key=lambda item: item.window_seconds)


class CommandCooldownConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    windows: list[CommandCooldownWindowConfig] = Field(
        default_factory=_default_command_cooldown_windows
    )
    cooldown_message: str = "操作过于频繁，请 {remaining_seconds} 秒后再试。"
    in_progress_message: str = "该命令正在处理中，请等待当前操作完成。"
    duplicate_window_seconds: float = Field(default=60.0, gt=0)
    duplicate_message: str = "该指令重复发送；后续重复不再提醒。"
    mention_initial_window_seconds: float = Field(default=600.0, gt=0)
    mention_initial_max_responses: int = Field(default=3, ge=1)
    commands: dict[str, list[CommandCooldownWindowConfig]] = Field(default_factory=dict)

    @field_validator("cooldown_message")
    @classmethod
    def validate_cooldown_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError(COMMAND_COOLDOWN_MESSAGE_REQUIRED_ERROR)
        try:
            fields = {
                field_name
                for _literal, field_name, _format_spec, _conversion in (
                    Formatter().parse(message)
                )
                if field_name is not None
            }
        except ValueError as exc:
            raise ValueError(COMMAND_COOLDOWN_MESSAGE_FORMAT_ERROR) from exc
        if fields - {"remaining_seconds"}:
            raise ValueError(COMMAND_COOLDOWN_MESSAGE_FORMAT_ERROR)
        try:
            message.format(remaining_seconds=1)
        except (KeyError, ValueError, AttributeError, IndexError) as exc:
            raise ValueError(COMMAND_COOLDOWN_MESSAGE_FORMAT_ERROR) from exc
        return message

    @field_validator("in_progress_message")
    @classmethod
    def validate_in_progress_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError(COMMAND_COOLDOWN_IN_PROGRESS_REQUIRED_ERROR)
        return message

    @field_validator("duplicate_message")
    @classmethod
    def validate_duplicate_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError(COMMAND_COOLDOWN_DUPLICATE_REQUIRED_ERROR)
        return message

    @field_validator("windows")
    @classmethod
    def validate_windows(
        cls,
        value: list[CommandCooldownWindowConfig],
    ) -> list[CommandCooldownWindowConfig]:
        return _normalize_command_cooldown_windows(value, required=True)

    @field_validator("commands")
    @classmethod
    def normalize_commands(
        cls,
        value: dict[str, list[CommandCooldownWindowConfig]],
    ) -> dict[str, list[CommandCooldownWindowConfig]]:
        normalized: dict[str, list[CommandCooldownWindowConfig]] = {}
        for raw_key, windows in value.items():
            key = raw_key.strip()
            if not key:
                raise ValueError(COMMAND_COOLDOWN_EMPTY_ID_ERROR)
            normalized[key] = _normalize_command_cooldown_windows(
                windows,
                required=False,
            )
        return normalized

    def windows_for(
        self,
        command_id: str,
    ) -> tuple[CommandCooldownWindowConfig, ...]:
        return tuple(self.commands.get(command_id, self.windows))


class BotRoutingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    default_bot: BotReference | None = None
    bot_aliases: dict[str, int] = Field(default_factory=dict)
    groups: dict[str, BotReference] = Field(default_factory=dict)
    users: dict[str, BotReference] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        invalid_aliases = [
            alias
            for alias, bot_id in self.bot_aliases.items()
            if not alias.strip() or bot_id <= 0
        ]
        if invalid_aliases:
            msg = "messaging.bot_routing.bot_aliases contains invalid entries"
            raise ValueError(msg)

        invalid_targets = [
            f"messaging.bot_routing.{mapping_name}.{target}"
            for mapping_name, mapping in (
                ("groups", self.groups),
                ("users", self.users),
            )
            for target, bot_ref in mapping.items()
            if not target.strip() or self.resolve_bot_reference(bot_ref) is None
        ]
        if (
            self.default_bot is not None
            and self.resolve_bot_reference(self.default_bot) is None
        ):
            invalid_targets.append("messaging.bot_routing.default_bot")
        if invalid_targets:
            msg = "unknown or invalid bot reference(s): " + ", ".join(invalid_targets)
            raise ValueError(msg)
        return self

    def resolve_bot_reference(self, reference: BotReference) -> int | None:
        if isinstance(reference, int):
            return reference if reference > 0 else None
        normalized = reference.strip()
        if normalized in self.bot_aliases:
            return self.bot_aliases[normalized]
        if normalized.isdigit() and int(normalized) > 0:
            return int(normalized)
        return None


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


class MessageReplyAction(BaseMessageAction):
    at_user_ids: OneBotReferenceList = Field(default_factory=list)


class MessageCommandAction(MessageReplyAction):
    commands: NormalizedStringList = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_enabled_command_action(self) -> Self:
        if not self.id:
            raise ValueError(COMMAND_ID_REQUIRED_ERROR)
        if not _SCHEDULE_ID_PATTERN.fullmatch(self.id):
            raise ValueError(COMMAND_ID_FORMAT_ERROR)
        if self.enabled and not self.commands:
            raise ValueError(ENABLED_COMMANDS_REQUIRED_ERROR)
        return self


class MessageKeywordReplyAction(MessageReplyAction):
    keywords: NormalizedStringList = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_enabled_keyword_reply_action(self) -> Self:
        if not self.id:
            raise ValueError(COMMAND_ID_REQUIRED_ERROR)
        if not _SCHEDULE_ID_PATTERN.fullmatch(self.id):
            raise ValueError(COMMAND_ID_FORMAT_ERROR)
        if self.enabled and not self.keywords:
            raise ValueError(ENABLED_KEYWORDS_REQUIRED_ERROR)
        return self


class MessageMentionReplyAction(BaseMessageAction):
    user_ids: OneBotReferenceList = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_enabled_mention_reply_action(self) -> Self:
        if not self.id:
            raise ValueError(COMMAND_ID_REQUIRED_ERROR)
        if not _SCHEDULE_ID_PATTERN.fullmatch(self.id):
            raise ValueError(COMMAND_ID_FORMAT_ERROR)
        if self.enabled and not self.user_ids:
            raise ValueError(ENABLED_MENTION_USERS_REQUIRED_ERROR)
        return self


class MessageScheduledAction(BaseMessageAction):
    feature: str = "text_push"
    at_user_ids: OneBotReferenceList = Field(default_factory=list)
    time: str
    day_of_week: str | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_time_fields(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        legacy_hour = data.pop("hour", None)
        legacy_minute = data.pop("minute", None)
        if data.get("time") is not None or legacy_hour is None:
            return data

        try:
            hour = int(legacy_hour)
            minute = int(legacy_minute) if legacy_minute is not None else 0
        except (TypeError, ValueError) as exc:
            raise ValueError(SCHEDULE_TIME_ERROR) from exc
        data["time"] = f"{hour:02d}:{minute:02d}"
        return data

    @field_validator("time")
    @classmethod
    def normalize_time(cls, value: str) -> str:
        return normalize_daily_time(value, error_message=SCHEDULE_TIME_ERROR)

    @model_validator(mode="after")
    def validate_schedule_id(self) -> Self:
        schedule_id = self.id.strip()
        if not schedule_id:
            raise ValueError(SCHEDULE_ID_REQUIRED_ERROR)
        if not _SCHEDULE_ID_PATTERN.fullmatch(schedule_id):
            raise ValueError(SCHEDULE_ID_FORMAT_ERROR)
        return self


class OutboundRateLimitWindowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_seconds: float = Field(gt=0)
    max_messages: int = Field(ge=1)


def _default_outbound_rate_limit_windows() -> list[OutboundRateLimitWindowConfig]:
    return [
        OutboundRateLimitWindowConfig(window_seconds=60.0, max_messages=10),
        OutboundRateLimitWindowConfig(window_seconds=600.0, max_messages=30),
    ]


class OutboundRateLimitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    windows: list[OutboundRateLimitWindowConfig] = Field(
        default_factory=_default_outbound_rate_limit_windows
    )
    cooldown_message: str = "机器人消息已达到发送额度，后续消息可能延迟或被抑制。"

    @field_validator("cooldown_message")
    @classmethod
    def validate_cooldown_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError(OUTBOUND_RATE_LIMIT_MESSAGE_REQUIRED_ERROR)
        return message

    @field_validator("windows")
    @classmethod
    def validate_windows(
        cls,
        value: list[OutboundRateLimitWindowConfig],
    ) -> list[OutboundRateLimitWindowConfig]:
        if not value:
            raise ValueError(OUTBOUND_RATE_LIMIT_WINDOWS_REQUIRED_ERROR)
        seen: set[float] = set()
        for window in value:
            if window.window_seconds in seen:
                raise ValueError(OUTBOUND_RATE_LIMIT_WINDOWS_DUPLICATE_ERROR)
            seen.add(window.window_seconds)
        return sorted(value, key=lambda item: item.window_seconds)


class PushUnsubscribeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commands: NormalizedStringList = Field(default_factory=lambda: ["td", "退订"])
    restore_commands: NormalizedStringList = Field(
        default_factory=lambda: ["订阅", "恢复订阅", "推送管理"]
    )
    hint: str = "回复 TD 可管理推送订阅。"
    group_hint: str = (
        "发送 TD、订阅 或 推送管理 可查看推送订阅；"
        "群主/管理员可切换开关，发送 推送时间 管理提醒时间。"
    )

    @field_validator("hint", "group_hint")
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


class PushDeliveryConfig(BaseModel):
    """Adaptive batching for background fan-out messages."""

    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=3, ge=1)
    retry_batch_divisor: int = Field(default=3, ge=2)
    batch_delay_min_seconds: float = Field(default=2.0, ge=0)
    batch_delay_max_seconds: float = Field(default=5.0, ge=0)

    @model_validator(mode="after")
    def validate_batch_delay_range(self) -> Self:
        if self.batch_delay_max_seconds < self.batch_delay_min_seconds:
            raise ValueError(PUSH_DELIVERY_DELAY_RANGE_ERROR)
        return self


class RedPacketNoticeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    cooldown_seconds: float = Field(default=60.0, ge=0)


class MeetingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str = ""
    template: str = (
        "腾讯会议\n腾讯会议号：{meeting_number}\n点击链接直接加入：{meeting_url}"
    )
    commands: NormalizedStringList = Field(default_factory=lambda: ["开播", "会议"])


class TeamAuditWelcomeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
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
        "你加入战队审核群已经 {hours:g} 小时了，仍在审核群。\n"
        "审核群仅供入队审核使用；如果已完成审核、已加入主群，"
        "或不再申请加入战队，请退出本审核群。"
    )
    final_followup_enabled: bool = True
    final_followup_after_hours: float = Field(default=48.0, gt=0)
    final_followup_message: str = (
        "你加入战队审核群已经 {hours:g} 小时了，仍然还在审核群。\n"
        "如果已经加入主群，或者不想加入战队，请退出本审核群。"
    )
    @field_validator(
        "message",
        "followup_message",
        "final_followup_message",
    )
    @classmethod
    def validate_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError(TEAM_AUDIT_WELCOME_MESSAGE_REQUIRED_ERROR)
        return message

    @model_validator(mode="after")
    def validate_final_followup_time(self) -> Self:
        if (
            self.followup_enabled
            and self.final_followup_enabled
            and self.final_followup_after_hours <= self.followup_after_hours
        ):
            raise ValueError(TEAM_AUDIT_FINAL_FOLLOWUP_AFTER_HOURS_ERROR)
        return self


class MessageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_routing: BotRoutingConfig = Field(default_factory=BotRoutingConfig)
    command_cooldown: CommandCooldownConfig = Field(
        default_factory=CommandCooldownConfig
    )
    outbound_rate_limit: OutboundRateLimitConfig = Field(
        default_factory=OutboundRateLimitConfig
    )
    push_unsubscribe: PushUnsubscribeConfig = Field(
        default_factory=PushUnsubscribeConfig
    )
    push_delivery: PushDeliveryConfig = Field(default_factory=PushDeliveryConfig)
    red_packet_notice: RedPacketNoticeConfig = Field(
        default_factory=RedPacketNoticeConfig
    )
    commands: list[MessageCommandAction] = Field(default_factory=list)
    keyword_replies: list[MessageKeywordReplyAction] = Field(default_factory=list)
    mention_replies: list[MessageMentionReplyAction] = Field(default_factory=list)
    schedules: list[MessageScheduledAction] = Field(default_factory=list)
    meeting: MeetingConfig = Field(default_factory=MeetingConfig)
    team_audit_welcome: TeamAuditWelcomeConfig = Field(
        default_factory=TeamAuditWelcomeConfig
    )
    sendpic: SendpicBehaviorConfig = Field(default_factory=SendpicBehaviorConfig)

    @property
    def command_feature_keys(self) -> frozenset[str]:
        return frozenset(
            action.feature
            for action in (
                *self.commands,
                *self.keyword_replies,
                *self.mention_replies,
            )
        )

    @property
    def schedule_feature_keys(self) -> frozenset[str]:
        return frozenset(action.feature for action in self.schedules)

    @model_validator(mode="after")
    def validate_unique_schedule_ids(self) -> Self:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for task in self.schedules:
            if task.id in seen:
                duplicates.add(task.id)
            seen.add(task.id)
        if duplicates:
            raise DuplicateScheduleIdError.from_ids(duplicates)
        return self
