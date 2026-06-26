# SPDX-License-Identifier: MIT
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

from ironsbot.shared.config.parsing import string_list
from ironsbot.shared.config.time import (
    normalized_daily_time_csv,
    normalized_daily_times,
)

INVALID_RESTART_TIME_ERROR = (
    "APP_CONFIG.runtime.restart.times must contain daily HH:MM times, "
    'for example "04:30,16:10" or ["04:30","16:10"]'
)
INVALID_RECONNECT_TIME_ERROR = (
    "APP_CONFIG.runtime.headless_notice.reconnect_check_times must contain "
    "daily HH:MM times, "
    'for example "00:01,00:02" or ["00:01","00:02"]'
)
DEFAULT_BROADCAST_MESSAGE = "赛尔号已经开服了。"
SEERAPI_DATA_RELEASE = "https://github.com/Murmansk5000/seerapi/releases/download"
IRONSBOT_RELEASE = "https://github.com/Murmansk5000/IronsBot/releases/download"
VALID_LOG_LEVELS = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}
WorkflowInputValue = str | int | float | bool


class RemoteBuildStepConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    repository: str = ""
    workflow_id: str = ""
    ref: str = "main"
    timeout_seconds: float = Field(default=1200.0, gt=0)
    poll_interval_seconds: float = Field(default=10.0, gt=0)
    inputs: dict[str, WorkflowInputValue] = Field(default_factory=dict)

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.repository and self.workflow_id:
            return f"{self.repository}/{self.workflow_id}"
        return "unnamed workflow"


class RemoteBuildConfig(RemoteBuildStepConfig):
    enabled: bool = False
    steps: list[RemoteBuildStepConfig] = Field(default_factory=list)

    def build_steps(self) -> list[RemoteBuildStepConfig]:
        if self.steps:
            return list(self.steps)
        if not self.repository and not self.workflow_id:
            return []
        return [
            RemoteBuildStepConfig(
                name=self.name,
                repository=self.repository,
                workflow_id=self.workflow_id,
                ref=self.ref,
                timeout_seconds=self.timeout_seconds,
                poll_interval_seconds=self.poll_interval_seconds,
                inputs=dict(self.inputs),
            )
        ]


class DataSourceConfig(BaseModel):
    url: str
    fingerprint_url: str = ""
    interval_minutes: int = Field(default=60, gt=0)
    local_path: str
    remote_build: RemoteBuildConfig = Field(default_factory=RemoteBuildConfig)


class DataSyncConfig(BaseModel):
    on_startup: bool = False
    interval_enabled: bool = True
    sources: dict[str, DataSourceConfig] = Field(
        default_factory=lambda: {
            "seerapi": DataSourceConfig(
                url=f"{SEERAPI_DATA_RELEASE}/ironsbot-data-latest/ironsbot-data.sqlite",
                fingerprint_url=(
                    f"{SEERAPI_DATA_RELEASE}/ironsbot-data-latest/"
                    "ironsbot-data.sqlite.sha256"
                ),
                interval_minutes=60,
                local_path="data/ironsbot-data.sqlite",
            ),
            "aliases": DataSourceConfig(
                url=f"{IRONSBOT_RELEASE}/alias-db-latest/aliases-data.sqlite",
                fingerprint_url=(
                    f"{IRONSBOT_RELEASE}/alias-db-latest/"
                    "aliases-data.sqlite.sha256"
                ),
                interval_minutes=60,
                local_path="data/aliases-data.sqlite",
            ),
        }
    )


class StartupConfig(BaseModel):
    enabled: bool = True
    message: str = "机器人已开启。"
    delay: float = Field(default=0.0, ge=0)


class ServerStatusConfig(BaseModel):
    broadcast: bool = False
    broadcast_message: str = DEFAULT_BROADCAST_MESSAGE
    broadcast_cooldown_minutes: int = Field(default=1440, ge=0)

    @field_validator("broadcast_message")
    @classmethod
    def normalize_broadcast_message(cls, value: str) -> str:
        message = value.strip()
        return message or DEFAULT_BROADCAST_MESSAGE


class RestartConfig(BaseModel):
    enabled: bool = False
    times: str = "04:30"
    grace_seconds: float = Field(default=10.0, ge=0)
    signal_parent: bool = True

    @field_validator("times", mode="before")
    @classmethod
    def normalize_restart_times(cls, value: object) -> str:
        return normalized_daily_time_csv(
            value,
            error_message=INVALID_RESTART_TIME_ERROR,
        )

    @model_validator(mode="after")
    def validate_restart_times(self) -> Self:
        if self.enabled and not self.parsed_restart_times:
            raise ValueError(INVALID_RESTART_TIME_ERROR)
        return self

    @property
    def parsed_restart_times(self) -> list[str]:
        return normalized_daily_times(
            self.times,
            error_message=INVALID_RESTART_TIME_ERROR,
        )


class HeadlessNoticeConfig(BaseModel):
    login_notice: bool = True
    login_notice_message: str = (
        "无头米米号登录未成功。\n"
        "米米号：{user_id}\n"
        "状态：{reason}\n"
        "依赖米米号登录的功能可能不可用；请检查账号、MD5密码、网络或赛尔号服务器状态。"
    )
    state_notice: bool = True
    state_offline_message: str = (
        "无头米米号已掉线。\n"
        "米米号：{user_id}\n"
        "状态：{reason}\n"
        "来源：{source}"
    )
    state_online_message: str = (
        "无头米米号已恢复登录。\n"
        "米米号：{user_id}\n"
        "来源：{source}"
    )
    reconnect_check_times: str = "00:01,00:02"

    @field_validator("reconnect_check_times", mode="before")
    @classmethod
    def normalize_reconnect_times(cls, value: object) -> str:
        return normalized_daily_time_csv(
            value,
            error_message=INVALID_RECONNECT_TIME_ERROR,
        )

    @property
    def parsed_reconnect_check_times(self) -> list[str]:
        return normalized_daily_times(
            self.reconnect_check_times,
            error_message=INVALID_RECONNECT_TIME_ERROR,
        )


class HelpConfig(BaseModel):
    ignored_plugins: list[str] = Field(default_factory=list)

    @field_validator("ignored_plugins", mode="before")
    @classmethod
    def normalize_ignored_plugins(cls, value: object) -> object:
        return string_list(value)


class SuperuserPriorityConfig(BaseModel):
    enabled: bool = True
    wait_timeout_seconds: float = Field(default=300.0, ge=0)


class MatcherPriorityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    about: int = Field(default=0, ge=0)
    help: int = Field(default=0, ge=0)
    help_hint: int = Field(default=0, ge=0)
    ai_group_at: int = Field(default=-1, ge=-100)
    ai_mention_guard: int = Field(default=-1, ge=-100)
    ai_chat: int = Field(default=99, ge=0)
    ai_intent: int = Field(default=4, ge=0)
    seer_query: int = Field(default=2, ge=0)
    seer_player: int = Field(default=1, ge=0)
    seer_rank_help: int = Field(default=2, ge=0)
    team_shortcut: int = Field(default=2, ge=0)
    bilibili: int = Field(default=1, ge=0)
    sendpic: int = Field(default=1, ge=0)
    server_status: int = Field(default=0, ge=0)
    server_status_admin: int = Field(default=1, ge=0)
    message_commands: int = Field(default=4, ge=0)
    meeting: int = Field(default=5, ge=0)
    activity: int = Field(default=5, ge=0)
    db_sync: int = Field(default=5, ge=0)
    team_audit: int = Field(default=5, ge=0)


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_enabled: bool = False
    file_path: str = "/app/logs/ironsbot.log"
    file_level: str = "INFO"
    error_file_enabled: bool = False
    error_file_path: str = "/app/logs/ironsbot.error.log"
    rotation: str = "20 MB"
    retention: str = "14 days"
    compression: str | None = "zip"

    @field_validator("file_level")
    @classmethod
    def normalize_file_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in VALID_LOG_LEVELS:
            msg = (
                "runtime.logging.file_level must be one of "
                f"{sorted(VALID_LOG_LEVELS)}"
            )
            raise ValueError(msg)
        return level

    @field_validator("file_path", "error_file_path", "rotation", "retention")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "runtime.logging fields must not be empty"
            raise ValueError(msg)
        return normalized

    @field_validator("compression", mode="before")
    @classmethod
    def normalize_optional_string(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class HeadlessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login_server_addr: str = "https://seer-login-ip.61.com/unity-ip.txt"
    heartbeat_interval: float = 300
    reconnect_retries: int = -1
    reconnect_delay: float = 5.0
    reconnect_delay_max: float = 120.0


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_sync: DataSyncConfig = Field(default_factory=DataSyncConfig)
    headless: HeadlessConfig = Field(default_factory=HeadlessConfig)
    headless_notice: HeadlessNoticeConfig = Field(default_factory=HeadlessNoticeConfig)
    startup_notice: StartupConfig = Field(default_factory=StartupConfig)
    server_status: ServerStatusConfig = Field(default_factory=ServerStatusConfig)
    restart: RestartConfig = Field(default_factory=RestartConfig)
    help: HelpConfig = Field(default_factory=HelpConfig)
    priority: SuperuserPriorityConfig = Field(default_factory=SuperuserPriorityConfig)
    matcher_priority: MatcherPriorityConfig = Field(
        default_factory=MatcherPriorityConfig
    )
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


__all__ = [
    "DEFAULT_BROADCAST_MESSAGE",
    "INVALID_RECONNECT_TIME_ERROR",
    "INVALID_RESTART_TIME_ERROR",
    "IRONSBOT_RELEASE",
    "SEERAPI_DATA_RELEASE",
    "DataSourceConfig",
    "DataSyncConfig",
    "HeadlessConfig",
    "HeadlessNoticeConfig",
    "HelpConfig",
    "LoggingConfig",
    "MatcherPriorityConfig",
    "RemoteBuildConfig",
    "RemoteBuildStepConfig",
    "RestartConfig",
    "RuntimeConfig",
    "ServerStatusConfig",
    "StartupConfig",
    "SuperuserPriorityConfig",
]
