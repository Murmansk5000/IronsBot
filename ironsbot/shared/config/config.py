# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.ai import AiConfig
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
    unique_items,
)
from ironsbot.shared.config.time import (
    normalize_daily_time,
)

INVALID_INTERVAL_TIME_ERROR = (
    "APP_CONFIG.bilibili.polling.windows time must use HH:MM"
)

BiliPushMode = Literal["full", "link"]
DEFAULT_BILI_SUPPRESS_PATTERNS = [
    "恭喜.*获得",
    "记得及时查看私信通知",
    "中奖",
    "抽奖结果",
]
DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS = 300.0

KNOWN_FEATURES = frozenset(
    {
        "seer",
        "image",
        "rank",
        "meeting",
        "text",
        "text_push",
        "activity_link",
        "activity_link_push",
        "seerinfo",
        "bili_query",
        "bili_push",
        "activity_query",
        "activity_push",
        "server_status_query",
        "server_status_push",
        "team",
        "ai_chat",
        "ai_intent",
        "admin_notice",
    }
)
FEATURE_ALIASES: dict[str, frozenset[str]] = {
    "all": KNOWN_FEATURES - {"admin_notice"},
    "custom": frozenset(
        {
            "seer",
            "image",
            "rank",
            "bili_query",
            "activity_query",
            "server_status_query",
        }
    ),
    "bili": frozenset({"bili_query", "bili_push"}),
    "activity": frozenset({"activity_query", "activity_push"}),
    "server_status": frozenset({"server_status_query", "server_status_push"}),
    "text": frozenset({"text", "activity_link", "seerinfo"}),
    "text_push": frozenset({"text_push", "activity_link_push"}),
    "message": frozenset(
        {
            "text",
            "text_push",
            "activity_link",
            "activity_link_push",
            "seerinfo",
        }
    ),
}


def _normalize_mode(value: object) -> object:
    if value is None or value == "":
        return value
    mode = str(value).strip().lower()
    if mode not in {"full", "link"}:
        msg = "APP_CONFIG.bilibili push mode must be full or link"
        raise ValueError(msg)
    return mode


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


class BiliIntervalWindow(BaseModel):
    start: str
    end: str
    minutes: int = Field(gt=0)

    @field_validator("start", "end")
    @classmethod
    def validate_hhmm(cls, value: str) -> str:
        return normalize_daily_time(
            value,
            error_message=INVALID_INTERVAL_TIME_ERROR,
        )


class BiliStorageConfig(BaseModel):
    data_dir: Path = Path("data/bilibili_monitor")
    history_max_items: int = Field(default=1000, ge=1)


class BiliPollingConfig(BaseModel):
    default_minutes: int = Field(default=30, gt=0)
    windows: list[BiliIntervalWindow] = Field(
        default_factory=lambda: [
            BiliIntervalWindow(start="07:00", end="23:00", minutes=5)
        ]
    )


class BiliPushTargetConfig(BaseModel):
    uids: list[int] = Field(default_factory=list)
    mode: BiliPushMode | None = None
    uid_modes: dict[int, BiliPushMode] = Field(default_factory=dict)

    @field_validator("uids", mode="before")
    @classmethod
    def normalize_uids(cls, value: object) -> object:
        return int_list(value)

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: object) -> object:
        return _normalize_mode(value)

    @field_validator("uid_modes", mode="before")
    @classmethod
    def normalize_uid_modes(cls, value: object) -> object:
        parsed = json_object(value, name="APP_CONFIG.bilibili.push uid_modes")
        result: dict[int, BiliPushMode] = {}
        for raw_uid, raw_mode in parsed.items():
            uid = int(raw_uid)
            mode = _normalize_mode(raw_mode)
            if mode in {"full", "link"}:
                result[uid] = mode
        return result


class BiliPushConfig(BaseModel):
    default_mode: BiliPushMode = "full"
    groups: dict[str, BiliPushTargetConfig] = Field(default_factory=dict)
    users: dict[str, BiliPushTargetConfig] = Field(default_factory=dict)

    @field_validator("default_mode", mode="before")
    @classmethod
    def normalize_default_mode(cls, value: object) -> object:
        return _normalize_mode(value)

    @field_validator("groups", "users", mode="before")
    @classmethod
    def normalize_targets(cls, value: object) -> object:
        parsed = json_object(value, name="APP_CONFIG.bilibili.push targets")
        result: dict[str, object] = {}
        for raw_ref, raw_config in parsed.items():
            ref = str(raw_ref).strip()
            if not ref:
                continue

            if raw_config is None or raw_config == "":
                result[ref] = {}
            elif (
                isinstance(raw_config, Iterable)
                and not isinstance(raw_config, str | bytes | Mapping)
            ):
                result[ref] = {"uids": list(raw_config)}
            else:
                result[ref] = raw_config
        return result


class BiliFilterConfig(BaseModel):
    suppress_push_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_BILI_SUPPRESS_PATTERNS)
    )

    @field_validator("suppress_push_patterns", mode="before")
    @classmethod
    def normalize_patterns(cls, value: object) -> object:
        return string_list(value)


class BiliConfig(BaseModel):
    uids: list[int] = Field(default_factory=lambda: [1310714247])
    storage: BiliStorageConfig = Field(default_factory=BiliStorageConfig)
    polling: BiliPollingConfig = Field(default_factory=BiliPollingConfig)
    push: BiliPushConfig = Field(default_factory=BiliPushConfig)
    filters: BiliFilterConfig = Field(default_factory=BiliFilterConfig)
    login_notice_cooldown_seconds: float = Field(
        default=DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS,
        ge=0,
    )

    @field_validator("uids", mode="before")
    @classmethod
    def normalize_uids(cls, value: object) -> object:
        return int_list(value)


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


class FeaturePolicyConfig(BaseModel):
    group_aliases: dict[str, int] = Field(default_factory=dict)
    user_aliases: dict[str, int] = Field(default_factory=dict)
    feature_group_policy: dict[str, list[str]] = Field(default_factory=dict)
    feature_user_policy: dict[str, list[str]] = Field(default_factory=dict)
    feature_superuser_bypass: bool = True

    @field_validator("group_aliases", "user_aliases", mode="before")
    @classmethod
    def normalize_aliases(cls, value: object) -> object:
        return _coerce_int_mapping(value)

    @field_validator("feature_group_policy", "feature_user_policy", mode="before")
    @classmethod
    def normalize_policy(cls, value: object) -> object:
        return _coerce_policy_mapping(value)


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


def unique_ints(values: Iterable[int]) -> list[int]:
    return unique_items(values)
