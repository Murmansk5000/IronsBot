# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.ai import AiConfig
from ironsbot.config.models.bilibili import BiliConfig
from ironsbot.config.models.feature import FeaturePolicyConfig
from ironsbot.config.models.message import (
    MeetingConfig,
    MessageActionsConfig,
    PicConfig,
    SendpicConfig,
)
from ironsbot.config.models.runtime import (
    DataSyncConfig,
    HeadlessNoticeConfig,
    HelpConfig,
    RestartConfig,
    ServerStatusConfig,
    StartupConfig,
    SuperuserPriorityConfig,
)
from ironsbot.config.models.seer import (
    RenderConfig,
    SeerQueryConfig,
    TeamConfig,
)
from ironsbot.shared.config.parsing import (
    int_list,
    json_object,
    nested_json_config,
    string_list,
)

if TYPE_CHECKING:
    from pathlib import Path

def _coerce_int_mapping(value: object) -> dict[str, int]:
    parsed = json_object(value, name="feature policy aliases")
    result: dict[str, int] = {}
    for raw_key, raw_value in parsed.items():
        key = str(raw_key).strip()
        if key:
            result[key] = int(raw_value)
    return result


def _coerce_policy_mapping(value: object) -> dict[str, list[str]]:
    parsed = json_object(value, name="feature policy")
    result: dict[str, list[str]] = {}
    for raw_key, raw_features in parsed.items():
        key = str(raw_key).strip()
        if key:
            result[key] = string_list(raw_features)
    return result


class ModulesConfig(BaseModel):
    ai: AiConfig = Field(default_factory=AiConfig)
    bilibili: BiliConfig = Field(default_factory=BiliConfig)
    message: MessageActionsConfig = Field(default_factory=MessageActionsConfig)
    seer: SeerQueryConfig = Field(default_factory=SeerQueryConfig)
    activity: ActivityConfig = Field(default_factory=ActivityConfig)
    team: TeamConfig = Field(default_factory=TeamConfig)
    meeting: MeetingConfig = Field(default_factory=MeetingConfig)
    startup: StartupConfig = Field(default_factory=StartupConfig)
    server_status: ServerStatusConfig = Field(default_factory=ServerStatusConfig)
    restart: RestartConfig = Field(default_factory=RestartConfig)
    headless_notice: HeadlessNoticeConfig = Field(default_factory=HeadlessNoticeConfig)
    help: HelpConfig = Field(default_factory=HelpConfig)
    priority: SuperuserPriorityConfig = Field(default_factory=SuperuserPriorityConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    sendpic: SendpicConfig = Field(default_factory=SendpicConfig)


class Config(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    ai_key: str = ""
    data_sync_config: DataSyncConfig = Field(default_factory=DataSyncConfig)
    headless_seer_login_server_addr: str = "https://seer-login-ip.61.com/unity-ip.txt"
    headless_seer_user_id: int | None = Field(
        default=None,
        description="米米号",
        ge=10001,
    )
    headless_seer_password: str | None = None
    headless_seer_heartbeat_interval: float = 300
    headless_seer_reconnect_retries: int = -1
    headless_seer_reconnect_delay: float = 5.0
    headless_seer_reconnect_delay_max: float = 120.0
    team_ids: list[int] = Field(default_factory=list)
    team_resource_users: list[int] = Field(default_factory=list)
    modules: ModulesConfig = Field(default_factory=ModulesConfig)
    group_aliases: dict[str, int] = Field(default_factory=dict)
    user_aliases: dict[str, int] = Field(default_factory=dict)
    feature_group_policy: dict[str, list[str]] = Field(default_factory=dict)
    feature_user_policy: dict[str, list[str]] = Field(default_factory=dict)
    feature_superuser_bypass: bool = True

    @field_validator("modules", mode="before")
    @classmethod
    def normalize_modules(cls, value: object) -> object:
        return nested_json_config(value, ModulesConfig, name="APP_CONFIG")

    @field_validator("data_sync_config", mode="before")
    @classmethod
    def normalize_data_sync_config(cls, value: object) -> object:
        return nested_json_config(
            value,
            DataSyncConfig,
            name="APP_CONFIG.runtime.data_sync",
        )

    @field_validator("team_ids", "team_resource_users", mode="before")
    @classmethod
    def normalize_int_ids(cls, value: object) -> object:
        return int_list(value)

    @field_validator("group_aliases", "user_aliases", mode="before")
    @classmethod
    def normalize_aliases(cls, value: object) -> object:
        return _coerce_int_mapping(value)

    @field_validator("feature_group_policy", "feature_user_policy", mode="before")
    @classmethod
    def normalize_policy(cls, value: object) -> object:
        return _coerce_policy_mapping(value)

    @property
    def ai_config(self) -> AiConfig:
        return self.modules.ai

    @property
    def bili_config(self) -> BiliConfig:
        return self.modules.bilibili

    @property
    def msg_config(self) -> MessageActionsConfig:
        return self.modules.message

    @property
    def seer_query_config(self) -> SeerQueryConfig:
        return self.modules.seer

    @property
    def activity_config(self) -> ActivityConfig:
        return self.modules.activity

    @property
    def team_config(self) -> TeamConfig:
        return self.modules.team

    @property
    def meeting_config(self) -> MeetingConfig:
        return self.modules.meeting

    @property
    def startup_config(self) -> StartupConfig:
        return self.modules.startup

    @property
    def server_status_config(self) -> ServerStatusConfig:
        return self.modules.server_status

    @property
    def bot_restart_config(self) -> RestartConfig:
        return self.modules.restart

    @property
    def headless_notice_config(self) -> HeadlessNoticeConfig:
        return self.modules.headless_notice

    @property
    def help_ignored_plugins(self) -> list[str]:
        return self.modules.help.ignored_plugins

    @property
    def superuser_priority(self) -> bool:
        return self.modules.priority.enabled

    @property
    def superuser_priority_wait_timeout_seconds(self) -> float:
        return self.modules.priority.wait_timeout_seconds

    @property
    def render_config(self) -> RenderConfig:
        return self.modules.render

    @property
    def sendpic_config(self) -> SendpicConfig:
        return self.modules.sendpic

    @property
    def sendpic_cnb_token(self) -> str | None:
        return self.modules.sendpic.cnb_token

    @property
    def sendpic_cnb_repo(self) -> str | None:
        return self.modules.sendpic.cnb_repo

    @property
    def sendpic_local_root(self) -> Path:
        return self.modules.sendpic.local_root

    @property
    def sendpic_configs(self) -> list[PicConfig]:
        return self.modules.sendpic.configs

    @property
    def sendpic_enabled_ids(self) -> frozenset[str]:
        return self.modules.sendpic.enabled_ids

    @property
    def feature_policy(self) -> FeaturePolicyConfig:
        return FeaturePolicyConfig(
            group_aliases=self.group_aliases,
            user_aliases=self.user_aliases,
            feature_group_policy=self.feature_group_policy,
            feature_user_policy=self.feature_user_policy,
            feature_superuser_bypass=self.feature_superuser_bypass,
        )
