# SPDX-License-Identifier: MIT
from __future__ import annotations

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
from ironsbot.core.time import normalize_daily_time

INVALID_INTERVAL_TIME_ERROR = "bilibili.polling.windows time must use HH:MM"

BiliPushMode = Literal["full", "link"]
DEFAULT_BILI_ACCOUNT_ALIAS = "seer"
DEFAULT_BILI_ACCOUNT_UID = 1310714247
DEFAULT_BILI_PUSH_CONTENT_MAX_CHARS = 800
DEFAULT_BILI_PUSH_SUMMARY_MAX_CHARS = 500
DEFAULT_BILI_SUPPRESS_PATTERNS = [
    "恭喜",
    "恭喜.*获得",
    "记得及时查看私信通知",
    "中奖",
    "抽奖结果",
]
DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS = 300.0


def truncate_bilibili_text(text: str, max_chars: int) -> str:
    """Keep a long dynamic readable without splitting a sentence or list item."""

    normalized = "\n".join(
        line.strip() for line in text.splitlines() if line.strip()
    )
    if len(normalized) <= max_chars:
        return normalized
    clipped = normalized[:max_chars]
    boundaries = [
        index
        for index, character in enumerate(clipped)
        if character in "。！？；\n"
    ]
    if boundaries and boundaries[-1] >= max_chars // 3:
        return clipped[: boundaries[-1] + 1].rstrip()
    return clipped.rstrip("，、：:；;-. ") + "……"


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


def _normalize_account_alias(value: object) -> str:
    return str(value).strip().lower()


def _account_alias_list(value: object) -> list[str]:
    return [
        alias
        for raw_alias in string_list(value)
        if (alias := _normalize_account_alias(raw_alias))
    ]


def _mode_mapping(value: object) -> dict[str, BiliPushMode]:
    parsed = json_object(value, name="bilibili.push.modes")
    result: dict[str, BiliPushMode] = {}
    for raw_alias, raw_mode in parsed.items():
        alias = _normalize_account_alias(raw_alias)
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


class BiliStorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_dir: Path = Path("data/bilibili_monitor")
    history_max_items: int = Field(default=1000, ge=1)


class BiliPollingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_minutes: int = Field(default=30, gt=0)
    windows: list[BiliIntervalWindow] = Field(
        default_factory=lambda: [
            BiliIntervalWindow(start="07:00", end="23:00", minutes=5)
        ]
    )


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
    accounts: _BiliAccountAliases = Field(
        default_factory=lambda: [DEFAULT_BILI_ACCOUNT_ALIAS]
    )
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


class BiliConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accounts: dict[str, BiliAccountConfig] = Field(
        default_factory=lambda: {
            DEFAULT_BILI_ACCOUNT_ALIAS: BiliAccountConfig(uid=DEFAULT_BILI_ACCOUNT_UID)
        }
    )
    storage: BiliStorageConfig = Field(default_factory=BiliStorageConfig)
    polling: BiliPollingConfig = Field(default_factory=BiliPollingConfig)
    push: BiliPushConfig = Field(default_factory=BiliPushConfig)
    filters: BiliFilterConfig = Field(default_factory=BiliFilterConfig)
    login_notice_cooldown_seconds: float = Field(
        default=DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS,
        ge=0,
    )

    @field_validator("accounts", mode="before")
    @classmethod
    def normalize_accounts(cls, value: object) -> object:
        parsed = json_object(value, name="bilibili.accounts")
        result: dict[str, object] = {
            DEFAULT_BILI_ACCOUNT_ALIAS: {
                "uid": DEFAULT_BILI_ACCOUNT_UID,
            }
        }
        for raw_alias, raw_config in parsed.items():
            alias = _normalize_account_alias(raw_alias)
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
