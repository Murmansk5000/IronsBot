# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
INVALID_SEER_PREVIEW_TIME_ERROR = (
    "bilibili.seer_categories.preview_windows time must use HH:MM"
)

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
SeerDynamicCategory = Literal[
    "lottery",
    "version_preview",
    "version_guide",
    "pet",
    "skin",
    "skill_showcase",
    "autocard",
    "competition",
    "story",
    "event",
    "interaction",
    "other",
]
SEER_DYNAMIC_CATEGORIES: tuple[SeerDynamicCategory, ...] = (
    "lottery",
    "version_preview",
    "version_guide",
    "pet",
    "skin",
    "skill_showcase",
    "autocard",
    "competition",
    "story",
    "event",
    "interaction",
    "other",
)
DEFAULT_SEER_MUTED_CATEGORIES: tuple[SeerDynamicCategory, ...] = ("lottery",)
DEFAULT_SEER_CATEGORY_PATTERNS: dict[str, list[str]] = {
    "lottery": ["抽奖", "中奖", "私信通知", "抽奖结果"],
    "version_preview": ["新版本.*即将到来", "查看下方长图"],
    "version_guide": ["一图掌握", "版本更新指引", "版本福利"],
    "pet": ["全新精灵", "精灵觉醒", "精灵.*即将登场"],
    "skin": ["全新皮肤", "限定皮肤", "皮肤.*返场", "皮肤.*即将登场"],
    "skill_showcase": ["技能特效抢先看"],
    "autocard": ["群星牌", "元素王座", "卡牌", "小小精灵"],
    "competition": ["大师赛", "小师赛", "赛事", "比赛", "赛程", "直播"],
    "story": ["灵渊", "玄武复活", "全新剧情", "主线故事"],
    "event": ["联动", "主题站", "通行证", "限时活动", "活动福利"],
    "interaction": ["投票", "应援", "报名", "问卷", "创作激励", "征集"],
}
DEFAULT_SEER_PREVIEW_WINDOW_PATTERNS = ["新版本", "即将到来", "长图"]
DEFAULT_SEER_PREVIEW_WEEKDAYS = ["mon", "wed"]


def truncate_bilibili_text(text: str, max_chars: int) -> str:
    """Keep a long dynamic readable without splitting a sentence or list item."""

    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(normalized) <= max_chars:
        return normalized
    clipped = normalized[:max_chars]
    boundaries = [
        index for index, character in enumerate(clipped) if character in "。！？；\n"
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


class BiliSeerCategoryConfigError(ValueError):
    @classmethod
    def invalid_weekday(cls) -> BiliSeerCategoryConfigError:
        return cls(
            "bilibili.seer_categories.preview_windows weekdays must use mon..sun"
        )

    @classmethod
    def invalid_window_order(cls) -> BiliSeerCategoryConfigError:
        return cls("bilibili.seer_categories.preview_windows start must be before end")

    @classmethod
    def empty_account(cls) -> BiliSeerCategoryConfigError:
        return cls("bilibili.seer_categories.account must not be empty")

    @classmethod
    def invalid_timezone(cls, value: str) -> BiliSeerCategoryConfigError:
        return cls(f"bilibili.seer_categories.timezone is invalid: {value}")

    @classmethod
    def unknown_muted_categories(
        cls,
        categories: list[str],
    ) -> BiliSeerCategoryConfigError:
        return cls(
            "bilibili.seer_categories.default_muted_categories contains "
            f"unknown categories: {', '.join(categories)}"
        )

    @classmethod
    def invalid_regex(
        cls,
        field: str,
        pattern: str,
        error: re.error,
    ) -> BiliSeerCategoryConfigError:
        return cls(
            f"bilibili.seer_categories.{field} has invalid regex {pattern!r}: {error}"
        )


class BiliSeerPreviewWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekdays: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_SEER_PREVIEW_WEEKDAYS)
    )
    start: str = "17:00"
    end: str = "18:00"

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, values: list[str]) -> list[str]:
        valid = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        normalized = [value.strip().lower() for value in values if value.strip()]
        if not normalized or any(value not in valid for value in normalized):
            raise BiliSeerCategoryConfigError.invalid_weekday()
        return list(dict.fromkeys(normalized))

    @field_validator("start", "end")
    @classmethod
    def validate_hhmm(cls, value: str) -> str:
        return normalize_daily_time(
            value,
            error_message=INVALID_SEER_PREVIEW_TIME_ERROR,
        )

    @model_validator(mode="after")
    def validate_order(self) -> BiliSeerPreviewWindow:
        if self.start >= self.end:
            raise BiliSeerCategoryConfigError.invalid_window_order()
        return self


class BiliSeerCategoryConfig(BaseModel):
    """Target-level category routing for the configured official Seer account."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    account: str = DEFAULT_BILI_ACCOUNT_ALIAS
    timezone: str = "Asia/Shanghai"
    default_muted_categories: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_SEER_MUTED_CATEGORIES)
    )
    preview_windows: list[BiliSeerPreviewWindow] = Field(
        default_factory=lambda: [BiliSeerPreviewWindow()]
    )
    preview_window_patterns: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_SEER_PREVIEW_WINDOW_PATTERNS)
    )
    lottery_patterns: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_SEER_CATEGORY_PATTERNS["lottery"])
    )
    version_preview_patterns: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_SEER_CATEGORY_PATTERNS["version_preview"])
    )
    version_guide_patterns: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_SEER_CATEGORY_PATTERNS["version_guide"])
    )
    pet_patterns: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_SEER_CATEGORY_PATTERNS["pet"])
    )
    skin_patterns: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_SEER_CATEGORY_PATTERNS["skin"])
    )
    skill_showcase_patterns: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_SEER_CATEGORY_PATTERNS["skill_showcase"])
    )
    autocard_patterns: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_SEER_CATEGORY_PATTERNS["autocard"])
    )
    competition_patterns: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_SEER_CATEGORY_PATTERNS["competition"])
    )
    story_patterns: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_SEER_CATEGORY_PATTERNS["story"])
    )
    event_patterns: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_SEER_CATEGORY_PATTERNS["event"])
    )
    interaction_patterns: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_SEER_CATEGORY_PATTERNS["interaction"])
    )

    @field_validator("account")
    @classmethod
    def normalize_account(cls, value: str) -> str:
        normalized = _normalize_account_alias(value)
        if not normalized:
            raise BiliSeerCategoryConfigError.empty_account()
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise BiliSeerCategoryConfigError.invalid_timezone(value) from error
        return value

    @field_validator("default_muted_categories")
    @classmethod
    def validate_muted_categories(cls, values: list[str]) -> list[str]:
        invalid = sorted(set(values) - set(SEER_DYNAMIC_CATEGORIES))
        if invalid:
            raise BiliSeerCategoryConfigError.unknown_muted_categories(invalid)
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_patterns(self) -> BiliSeerCategoryConfig:
        for category, patterns in self.category_patterns().items():
            for pattern in patterns:
                self._validate_regex(f"{category}_patterns", pattern)
        for pattern in self.preview_window_patterns:
            self._validate_regex("preview_window_patterns", pattern)
        return self

    @staticmethod
    def _validate_regex(field: str, pattern: str) -> None:
        try:
            re.compile(pattern)
        except re.error as error:
            raise BiliSeerCategoryConfigError.invalid_regex(
                field,
                pattern,
                error,
            ) from error

    def category_patterns(self) -> dict[SeerDynamicCategory, list[str]]:
        return {
            "lottery": self.lottery_patterns,
            "version_preview": self.version_preview_patterns,
            "version_guide": self.version_guide_patterns,
            "pet": self.pet_patterns,
            "skin": self.skin_patterns,
            "skill_showcase": self.skill_showcase_patterns,
            "autocard": self.autocard_patterns,
            "competition": self.competition_patterns,
            "story": self.story_patterns,
            "event": self.event_patterns,
            "interaction": self.interaction_patterns,
        }


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
    seer_categories: BiliSeerCategoryConfig = Field(
        default_factory=BiliSeerCategoryConfig
    )
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
        _validate_account_ref(
            "bilibili.seer_categories.account",
            self.seer_categories.account,
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
