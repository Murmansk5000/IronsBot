# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ironsbot.shared.config.parsing import json_object, string_list
from ironsbot.shared.config.time import normalize_daily_time

INVALID_INTERVAL_TIME_ERROR = (
    "APP_CONFIG.bilibili.polling.windows time must use HH:MM"
)

BiliPushMode = Literal["full", "link"]
DEFAULT_BILI_ACCOUNT_ALIAS = "seer"
DEFAULT_BILI_ACCOUNT_UID = 1310714247
DEFAULT_BILI_ACCOUNT_ALIASES = {DEFAULT_BILI_ACCOUNT_ALIAS: DEFAULT_BILI_ACCOUNT_UID}
REMOVED_BILI_UID_FIELDS_ERROR = (
    "bilibili no longer accepts raw UID fields. Use account_aliases, "
    "default_accounts, extra_accounts, and account_modes instead."
)
DEFAULT_BILI_SUPPRESS_PATTERNS = [
    "恭喜",
    "恭喜.*获得",
    "记得及时查看私信通知",
    "中奖",
    "抽奖结果",
]
DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS = 300.0


def _normalize_mode(value: object) -> object:
    if value is None or value == "":
        return value
    mode = str(value).strip().lower()
    if mode not in {"full", "link"}:
        msg = "APP_CONFIG.bilibili push mode must be full or link"
        raise ValueError(msg)
    return mode


def _normalize_account_name(value: object) -> str:
    return str(value).strip().lower()


def _account_list(value: object) -> list[str]:
    return [
        account
        for raw_account in string_list(value)
        if (account := _normalize_account_name(raw_account))
    ]


def _reject_removed_fields(data: object, fields: set[str]) -> None:
    if not isinstance(data, dict):
        return
    removed = sorted(fields & set(data))
    if not removed:
        return
    msg = f"{REMOVED_BILI_UID_FIELDS_ERROR} Removed field(s): {', '.join(removed)}"
    raise ValueError(msg)


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
    extra_accounts: list[str] = Field(default_factory=list)
    mode: BiliPushMode | None = None
    account_modes: dict[str, BiliPushMode] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def reject_removed_uid_fields(cls, value: object) -> object:
        _reject_removed_fields(value, {"uids", "uid_modes"})
        return value

    @field_validator("extra_accounts", mode="before")
    @classmethod
    def normalize_extra_accounts(cls, value: object) -> object:
        return _account_list(value)

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: object) -> object:
        return _normalize_mode(value)

    @field_validator("account_modes", mode="before")
    @classmethod
    def normalize_account_modes(cls, value: object) -> object:
        parsed = json_object(value, name="APP_CONFIG.bilibili.push account_modes")
        result: dict[str, BiliPushMode] = {}
        for raw_account, raw_mode in parsed.items():
            account = _normalize_account_name(raw_account)
            mode = _normalize_mode(raw_mode)
            if account and mode in {"full", "link"}:
                result[account] = mode
        return result


class BiliPushConfig(BaseModel):
    default_mode: BiliPushMode = "full"
    default_accounts: list[str] = Field(
        default_factory=lambda: [DEFAULT_BILI_ACCOUNT_ALIAS]
    )
    groups: dict[str, BiliPushTargetConfig] = Field(default_factory=dict)
    users: dict[str, BiliPushTargetConfig] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def reject_removed_uid_fields(cls, value: object) -> object:
        _reject_removed_fields(value, {"default_uids"})
        return value

    @field_validator("default_mode", mode="before")
    @classmethod
    def normalize_default_mode(cls, value: object) -> object:
        return _normalize_mode(value)

    @field_validator("default_accounts", mode="before")
    @classmethod
    def normalize_default_accounts(cls, value: object) -> object:
        return _account_list(value)

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
    account_aliases: dict[str, int] = Field(
        default_factory=lambda: dict(DEFAULT_BILI_ACCOUNT_ALIASES)
    )
    storage: BiliStorageConfig = Field(default_factory=BiliStorageConfig)
    polling: BiliPollingConfig = Field(default_factory=BiliPollingConfig)
    push: BiliPushConfig = Field(default_factory=BiliPushConfig)
    filters: BiliFilterConfig = Field(default_factory=BiliFilterConfig)
    login_notice_cooldown_seconds: float = Field(
        default=DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS,
        ge=0,
    )

    @model_validator(mode="before")
    @classmethod
    def reject_removed_uid_fields(cls, value: object) -> object:
        _reject_removed_fields(value, {"uids"})
        return value

    @field_validator("account_aliases", mode="before")
    @classmethod
    def normalize_account_aliases(cls, value: object) -> object:
        parsed = json_object(value, name="APP_CONFIG.bilibili.account_aliases")
        result: dict[str, int] = dict(DEFAULT_BILI_ACCOUNT_ALIASES)
        for raw_alias, raw_uid in parsed.items():
            alias = _normalize_account_name(raw_alias)
            if not alias:
                continue
            uid = int(raw_uid)
            if uid > 0:
                result[alias] = uid
        return result

    @model_validator(mode="after")
    def validate_account_references(self) -> BiliConfig:
        aliases = set(self.account_aliases)
        for account in self.push.default_accounts:
            _validate_account_ref("bilibili.push.default_accounts", account, aliases)
        _validate_target_account_refs("bilibili.push.groups", self.push.groups, aliases)
        _validate_target_account_refs("bilibili.push.users", self.push.users, aliases)
        return self


class BilibiliConfig(BiliConfig):
    pass


def _validate_account_ref(location: str, account: str, aliases: set[str]) -> None:
    if account in aliases:
        return
    msg = f"Unknown Bilibili account alias in {location}: {account}"
    raise ValueError(msg)


def _validate_target_account_refs(
    location: str,
    targets: dict[str, BiliPushTargetConfig],
    aliases: set[str],
) -> None:
    for ref, target in targets.items():
        for account in target.extra_accounts:
            _validate_account_ref(f"{location}.{ref}.extra_accounts", account, aliases)
        for account in target.account_modes:
            _validate_account_ref(f"{location}.{ref}.account_modes", account, aliases)


__all__ = [
    "DEFAULT_BILI_ACCOUNT_ALIAS",
    "DEFAULT_BILI_ACCOUNT_ALIASES",
    "DEFAULT_BILI_ACCOUNT_UID",
    "DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS",
    "DEFAULT_BILI_SUPPRESS_PATTERNS",
    "INVALID_INTERVAL_TIME_ERROR",
    "REMOVED_BILI_UID_FIELDS_ERROR",
    "BiliConfig",
    "BiliFilterConfig",
    "BiliIntervalWindow",
    "BiliPollingConfig",
    "BiliPushConfig",
    "BiliPushMode",
    "BiliPushTargetConfig",
    "BiliStorageConfig",
    "BilibiliConfig",
]
