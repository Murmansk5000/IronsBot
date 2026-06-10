from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal

from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator

from ironsbot.custom_plugins.common.config_utils import (
    int_list,
    json_object,
    nested_json_config,
    string_list,
)
from ironsbot.custom_plugins.common.time_config import normalize_daily_time

BiliPushMode = Literal["full", "link"]

INVALID_INTERVAL_TIME_ERROR = "BILI_CONFIG.polling.windows time must use HH:MM"
DEFAULT_SUPPRESS_PATTERNS = [
    "恭喜.*获得",
    "记得及时查看私信通知",
    "中奖",
    "抽奖结果",
]


def _normalize_mode(value: object) -> object:
    if value is None or value == "":
        return value
    mode = str(value).strip().lower()
    if mode not in {"full", "link"}:
        msg = "BILI_CONFIG push mode must be full or link"
        raise ValueError(msg)
    return mode


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
        parsed = json_object(value, name="BILI_CONFIG.push uid_modes")
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
        parsed = json_object(value, name="BILI_CONFIG.push targets")
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
