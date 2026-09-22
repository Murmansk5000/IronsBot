# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from ironsbot.core.commands import (
    NormalizedStringList,
    json_object,
    string_list,
)
from ironsbot.core.time import (
    normalize_daily_time,
    normalize_daily_time_with_seconds,
)

INVALID_INTERVAL_TIME_ERROR = "bilibili.polling.windows time must use HH:MM"

BiliPushMode = Literal["full", "link"]
DEFAULT_BILI_PUSH_CONTENT_MAX_CHARS = 400
DEFAULT_BILI_PUSH_SUMMARY_MAX_CHARS = 250
DEFAULT_BILI_SUPPRESS_PATTERNS = [
    "恭喜",
    "恭喜.*获得",
    "记得及时查看私信通知",
    "中奖",
    "抽奖结果",
]
DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS = 300.0
MAX_CLOCK_SECOND = 59


class BiliPushTargetConfigError(ValueError):
    @classmethod
    def empty_onebot_target_reference(cls) -> BiliPushTargetConfigError:
        return cls("bilibili.push targets contain an empty OneBot target ref")


def _normalize_mode(value: object) -> BiliPushMode | None:
    if value is None or value == "":
        return None
    mode = str(value).strip().lower()
    if mode not in {"full", "link"}:
        msg = "bilibili push mode must be full or link"
        raise ValueError(msg)
    return cast("BiliPushMode", mode)


def normalize_account_alias(value: object) -> str:
    """Normalize one configured or user-supplied Bilibili account alias."""

    return str(value).strip().lower()


def _account_alias_list(value: object) -> list[str]:
    return [
        alias
        for raw_alias in string_list(value)
        if (alias := normalize_account_alias(raw_alias))
    ]


def _mode_mapping(value: object) -> dict[str, BiliPushMode]:
    parsed = json_object(value, name="bilibili.push.modes")
    result: dict[str, BiliPushMode] = {}
    for raw_alias, raw_mode in parsed.items():
        alias = normalize_account_alias(raw_alias)
        mode = _normalize_mode(raw_mode)
        if alias and mode is not None:
            result[alias] = mode
    return result


_BiliAccountAliases = Annotated[
    list[str],
    BeforeValidator(_account_alias_list),
]
_OptionalBiliPushMode = Annotated[
    BiliPushMode | None,
    BeforeValidator(_normalize_mode),
]
_RequiredBiliPushMode = Annotated[BiliPushMode, BeforeValidator(_normalize_mode)]
_BiliPushModes = Annotated[
    dict[str, BiliPushMode],
    BeforeValidator(_mode_mapping),
]


class BiliIntervalWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

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


class BiliBoostWindow(BaseModel):
    """Extra short polling burst around a recurring wall-clock release slot."""

    model_config = ConfigDict(extra="forbid")

    start: str
    end: str
    interval_minutes: int = Field(gt=0)
    offset_seconds: list[int] = Field(min_length=1)

    @field_validator("start", "end")
    @classmethod
    def validate_hhmmss(cls, value: str) -> str:
        return normalize_daily_time_with_seconds(
            value,
            error_message="bilibili.polling.boost_windows time must use HH:MM:SS",
        )

    @field_validator("offset_seconds")
    @classmethod
    def validate_offset_seconds(cls, value: list[int]) -> list[int]:
        if any(not 0 <= second <= MAX_CLOCK_SECOND for second in value):
            msg = (
                "bilibili.polling.boost_windows offset_seconds must be between 0 and 59"
            )
            raise ValueError(msg)
        if len(set(value)) != len(value):
            msg = (
                "bilibili.polling.boost_windows offset_seconds "
                "must not contain duplicates"
            )
            raise ValueError(msg)
        return sorted(value)


class BiliStorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_dir: Path = Path("data/bilibili_monitor")
    history_max_items: int = Field(default=1000, ge=1)


class BiliPollingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_minutes: int = Field(default=30, gt=0)
    check_second: int = Field(default=5, ge=0, le=MAX_CLOCK_SECOND)
    windows: list[BiliIntervalWindow] = Field(
        default_factory=lambda: [
            BiliIntervalWindow(start="07:00", end="23:00", minutes=5)
        ]
    )
    boost_windows: list[BiliBoostWindow] = Field(default_factory=list)


class BiliAccountConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: int = Field(gt=0)


class BiliPushTargetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accounts: _BiliAccountAliases = Field(default_factory=list)
    mode: _OptionalBiliPushMode = None
    modes: _BiliPushModes = Field(default_factory=dict)


class BiliPushConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: _RequiredBiliPushMode = "full"
    accounts: _BiliAccountAliases = Field(default_factory=list)
    # Per-account modes are opt-in TOML overrides. Targets otherwise inherit mode.
    modes: _BiliPushModes = Field(default_factory=dict)
    content_max_chars: int = Field(
        default=DEFAULT_BILI_PUSH_CONTENT_MAX_CHARS,
        ge=1,
    )
    summary_max_chars: int = Field(
        default=DEFAULT_BILI_PUSH_SUMMARY_MAX_CHARS,
        ge=1,
    )
    summary_use_ai: bool = True
    combine_images: bool = True
    groups: dict[str, BiliPushTargetConfig] = Field(default_factory=dict)
    users: dict[str, BiliPushTargetConfig] = Field(default_factory=dict)

    @field_validator("groups", "users", mode="before")
    @classmethod
    def normalize_targets(cls, value: object) -> object:
        parsed = json_object(value, name="bilibili.push targets")
        result: dict[str, object] = {}
        for raw_ref, raw_config in parsed.items():
            ref = str(raw_ref).strip()
            if not ref:
                raise BiliPushTargetConfigError.empty_onebot_target_reference()

            if raw_config is None or raw_config == "":
                result[ref] = {}
            else:
                result[ref] = raw_config
        return result


class BiliFilterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suppress_push_patterns: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_BILI_SUPPRESS_PATTERNS)
    )


class BiliDynamicCategoryConfig(BaseModel):
    """A configurable content category for one monitored Bilibili account."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    patterns: NormalizedStringList = Field(min_length=1)

    @field_validator("patterns")
    @classmethod
    def validate_patterns(cls, values: list[str]) -> list[str]:
        invalid = next(
            (pattern for pattern in values if not _is_valid_regex(pattern)),
            None,
        )
        if invalid is not None:
            msg = f"bilibili.category_subscriptions has invalid regex {invalid!r}"
            raise ValueError(msg)
        return values


class BiliAccountCategorySubscriptionConfig(BaseModel):
    """Category controls for a configured account, without account-specific code."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    categories: dict[str, BiliDynamicCategoryConfig] = Field(default_factory=dict)
    default_muted_categories: NormalizedStringList = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_muted_categories(self) -> BiliAccountCategorySubscriptionConfig:
        unknown = sorted(set(self.default_muted_categories) - set(self.categories))
        if unknown:
            msg = (
                "bilibili.category_subscriptions has unknown muted categories: "
                + ", ".join(unknown)
            )
            raise ValueError(msg)
        return self


class BiliCategorySubscriptionsConfig(BaseModel):
    """Optional, reusable category subscription rules keyed by account alias."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    accounts: dict[str, BiliAccountCategorySubscriptionConfig] = Field(
        default_factory=dict
    )

    @field_validator("accounts", mode="before")
    @classmethod
    def normalize_accounts(cls, value: object) -> object:
        parsed = json_object(value, name="bilibili.category_subscriptions.accounts")
        return {
            alias: account
            for raw_alias, account in parsed.items()
            if (alias := normalize_account_alias(raw_alias))
        }


class BiliConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accounts: dict[str, BiliAccountConfig] = Field(default_factory=dict)
    storage: BiliStorageConfig = Field(default_factory=BiliStorageConfig)
    polling: BiliPollingConfig = Field(default_factory=BiliPollingConfig)
    push: BiliPushConfig = Field(default_factory=BiliPushConfig)
    filters: BiliFilterConfig = Field(default_factory=BiliFilterConfig)
    category_subscriptions: BiliCategorySubscriptionsConfig = Field(
        default_factory=BiliCategorySubscriptionsConfig
    )
    login_notice_cooldown_seconds: float = Field(
        default=DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS,
        ge=0,
    )

    @field_validator("accounts", mode="before")
    @classmethod
    def normalize_accounts(cls, value: object) -> object:
        parsed = json_object(value, name="bilibili.accounts")
        result: dict[str, object] = {}
        for raw_alias, raw_config in parsed.items():
            alias = normalize_account_alias(raw_alias)
            if alias:
                result[alias] = raw_config
        return result

    @model_validator(mode="after")
    def validate_account_references(self) -> BiliConfig:
        accounts = set(self.accounts)
        for index, alias in enumerate(self.push.accounts):
            _validate_account_ref(
                f"bilibili.push.accounts[{index}]",
                alias,
                accounts,
            )
        for alias in self.push.modes:
            _validate_account_ref(
                f"bilibili.push.modes.{alias}",
                alias,
                accounts,
            )
        _validate_target_account_refs(
            "bilibili.push.groups",
            self.push.groups,
            accounts,
        )
        _validate_target_account_refs(
            "bilibili.push.users",
            self.push.users,
            accounts,
        )
        for alias in self.category_subscriptions.accounts:
            _validate_account_ref(
                f"bilibili.category_subscriptions.accounts.{alias}",
                alias,
                accounts,
            )
        return self


def _validate_account_ref(
    location: str,
    alias: str,
    accounts: set[str],
) -> None:
    if alias not in accounts:
        raise ValueError(  # noqa: TRY003
            f"unknown Bilibili account alias at {location}: {alias}"
        )


def _is_valid_regex(pattern: str) -> bool:
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


def _validate_target_account_refs(
    location: str,
    targets: dict[str, BiliPushTargetConfig],
    accounts: set[str],
) -> None:
    for ref, target in targets.items():
        for index, alias in enumerate(target.accounts):
            _validate_account_ref(
                f"{location}.{ref}.accounts[{index}]",
                alias,
                accounts,
            )
        for alias in target.modes:
            _validate_account_ref(
                f"{location}.{ref}.modes.{alias}",
                alias,
                accounts,
            )
