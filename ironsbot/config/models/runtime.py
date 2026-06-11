# SPDX-License-Identifier: MIT
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ironsbot.shared.config.config import (
    DataSyncConfig,
    HeadlessNoticeConfig,
    HelpConfig,
    RestartConfig,
    ServerStatusConfig,
    StartupConfig,
    SuperuserPriorityConfig,
)


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


__all__ = ["HeadlessConfig", "RuntimeConfig"]
