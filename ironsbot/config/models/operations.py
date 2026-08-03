# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

from ironsbot.core.time import (
    normalized_daily_time_csv,
    normalized_daily_times,
)

INVALID_RESTART_TIME_ERROR = (
    "operations.restart.times must contain daily HH:MM times, "
    'for example "04:30,16:10" or ["04:30","16:10"]'
)
INVALID_RECONNECT_TIME_ERROR = (
    "operations.headless_notice.reconnect_check_times must contain "
    "daily HH:MM times, "
    'for example "00:05" or ["00:05"]'
)
SEERAPI_DATA_RELEASE = "https://github.com/Murmansk-Seer/seerapi/releases/download"
IRONSBOT_RELEASE = "https://github.com/Murmansk5000/IronsBot/releases/download"
WorkflowInputValue = str | int | float | bool


class RemoteBuildStepConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    repository: str = ""
    workflow_id: str = ""
    ref: str = "main"
    timeout_seconds: float = Field(default=1200.0, gt=0)
    poll_interval_seconds: float = Field(default=10.0, gt=0)
    reuse_existing_run: bool = True
    reuse_existing_run_max_age_seconds: float = Field(default=3600.0, gt=0)
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
                reuse_existing_run=self.reuse_existing_run,
                reuse_existing_run_max_age_seconds=(
                    self.reuse_existing_run_max_age_seconds
                ),
                inputs=dict(self.inputs),
            )
        ]


class DataSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    fingerprint_url: str = ""
    interval_minutes: int = Field(default=60, gt=0)
    local_path: str
    remote_build: RemoteBuildConfig = Field(default_factory=RemoteBuildConfig)


class DataSyncConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    github_token: str = Field(default="", exclude=True, repr=False)
    on_startup: bool = True
    startup_trigger_remote_build: bool = False
    interval_enabled: bool = True
    sources: dict[str, DataSourceConfig] = Field(
        default_factory=lambda: {
            "seerapi": DataSourceConfig(
                url=f"{SEERAPI_DATA_RELEASE}/seerapi-data-latest/seerapi-data.sqlite",
                fingerprint_url=(
                    f"{SEERAPI_DATA_RELEASE}/seerapi-data-latest/"
                    "seerapi-data.sqlite.sha256"
                ),
                interval_minutes=60,
                local_path="data/seerapi-data.sqlite",
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
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    message: str = "机器人已开启。"
    delay: float = Field(default=0.0, ge=0)


class DockerUpdateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_on_startup: bool = True
    check_on_restart: bool = True
    image: str = "murmansk5000/ironsbot:latest"
    container_name: str = "ironsbot"
    docker_socket_path: str = "/var/run/docker.sock"
    watchtower_image: str = "containrrr/watchtower:latest"
    watchtower_docker_api_version: str = "1.40"
    timeout_seconds: float = Field(default=300.0, gt=0)
    registry_username: str = Field(default="", exclude=True, repr=False)
    registry_token: str = Field(default="", exclude=True, repr=False)

    @field_validator(
        "image",
        "container_name",
        "docker_socket_path",
        "watchtower_image",
        "watchtower_docker_api_version",
        "registry_username",
        "registry_token",
    )
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "operations.docker_update string fields must not be empty"
            raise ValueError(msg)
        return normalized


class PrivateExtensionsConfig(BaseModel):
    """Optional private extension package installed before the app boots."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    image: str = "murmansk5000/ironsbot-private:latest"
    archive_path: str = "/ironsbot_extensions"
    data_path: str = "data/private_extensions"
    timeout_seconds: float = Field(default=60.0, gt=0)
    settings: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @field_validator("image", "archive_path", "data_path")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "operations.private_extensions string fields must not be empty"
            raise ValueError(msg)
        return normalized


class RestartConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

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
        "离线时长：{offline_duration}\n"
        "来源：{source}"
    )
    reconnect_check_times: str = "00:05"

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


class HeadlessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login_server_addr: str = "https://seer-login-ip.61.com/unity-ip.txt"
    heartbeat_interval: float = 300
    request_timeout_seconds: float = Field(default=20.0, gt=0)
    reconnect_retries: int = -1
    reconnect_delay: float = 5.0
    reconnect_delay_max: float = 120.0
class OperationsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_sync: DataSyncConfig = Field(default_factory=DataSyncConfig)
    headless: HeadlessConfig = Field(default_factory=HeadlessConfig)
    headless_notice: HeadlessNoticeConfig = Field(default_factory=HeadlessNoticeConfig)
    startup_notice: StartupConfig = Field(default_factory=StartupConfig)
    docker_update: DockerUpdateConfig = Field(default_factory=DockerUpdateConfig)
    private_extensions: PrivateExtensionsConfig = Field(
        default_factory=PrivateExtensionsConfig
    )
    restart: RestartConfig = Field(default_factory=RestartConfig)
