from pathlib import Path
from typing import Literal

from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator

from ironsbot.custom_plugins.common.config_utils import (
    int_list,
    nested_json_config,
    string_list,
)
from ironsbot.custom_plugins.common.time_config import normalize_daily_time

INVALID_INTERVAL_TIME_ERROR = "BILI_CONFIG.polling.windows time must use HH:MM"
DEFAULT_SUPPRESS_PATTERNS = [
    "恭喜.*获得",
    "记得及时查看私信通知",
    "中奖",
    "抽奖结果",
]


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


class BiliPushConfig(BaseModel):
    default_mode: Literal["full", "link"] = "full"
    link_only_groups: list[str] = Field(default_factory=list)
    link_only_users: list[str] = Field(default_factory=list)

    @field_validator("link_only_groups", "link_only_users", mode="before")
    @classmethod
    def normalize_refs(cls, value: object) -> object:
        return string_list(value)


class BiliFilterConfig(BaseModel):
    suppress_push_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SUPPRESS_PATTERNS)
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

    @field_validator("uids", mode="before")
    @classmethod
    def normalize_uids(cls, value: object) -> object:
        return int_list(value)


class Config(BaseModel):
    bili_config: BiliConfig = Field(default_factory=BiliConfig)

    @field_validator("bili_config", mode="before")
    @classmethod
    def normalize_bili_config(cls, value: object) -> object:
        return nested_json_config(value, BiliConfig, name="BILI_CONFIG")


plugin_config = get_plugin_config(Config)
