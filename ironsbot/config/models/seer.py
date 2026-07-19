# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from ironsbot.core.commands import NormalizedStringList, string_list
from ironsbot.core.time import normalized_daily_times

if TYPE_CHECKING:
    from collections.abc import Iterable

PLAYER_SECTION_KEYS: tuple[str, ...] = (
    "basic",
    "appearance",
    "social",
    "collection",
    "rank",
    "autocard",
    "local_rank",
    "achievement",
    "peak",
    "titles",
    "pets",
    "stages",
    "battle",
    "raw",
)
TEAM_SECTION_KEYS: tuple[str, ...] = (
    "basic",
    "resource",
    "facilities",
    "status",
    "logo",
    "text",
)
RANK_PAGE_REFRESH_TIME_ERROR = (
    "seer.rank.page_refresh.times must contain daily HH:MM times"
)
RANK_PAGE_REFRESH_INTERVAL_OFFSET_ERROR = (
    "seer.rank.page_refresh.interval_offset_minutes must be smaller than "
    "interval_minutes"
)
RANK_PAGE_REFRESH_PAGES_PER_RUN_MIN_ERROR = (
    "seer.rank.page_refresh.pages_per_run_min must not be greater than pages_per_run"
)
RANK_PAGE_REFRESH_ACTIVE_TIME_ERROR = (
    "seer.rank.page_refresh active_start/active_end must be HH:MM times"
)
RANK_PAGE_REFRESH_ACTIVE_PAIR_ERROR = (
    "seer.rank.page_refresh.active_start and active_end must be configured together"
)
TEAM_RESOURCE_TIME_ERROR = (
    "seer.team_resource.times must contain daily HH:MM times"
)
DEFAULT_RANK_PAGE_REFRESH_TIMES = (
    "01:15",
    "01:45",
    "02:15",
    "02:45",
    "03:15",
    "03:45",
    "04:15",
    "04:45",
)
DEFAULT_RANK_PAGE_REFRESH_KEYS = (
    "图鉴积分",
    "成就点数",
    "精灵图鉴",
    "皮肤图鉴",
    "套装图鉴",
    "部件图鉴",
    "座驾图鉴",
    "刻印图鉴",
    "群星牌",
    "竞技段位",
    "狂野段位",
    "专家段位",
)
MAX_RANK_DISPLAY_LIMIT = 100


def _coerce_sections(value: object) -> object:
    if value is None or value == "":
        return ["all"]

    return string_list(value)


def _normalize_sections(
    value: Iterable[str],
    allowed: tuple[str, ...],
    *,
    path: str,
) -> list[str]:
    normalized: list[str] = []
    unknown: list[str] = []

    for raw in value:
        section = str(raw).strip().lower()
        if not section:
            continue
        if section in {"*", "all"}:
            return list(allowed)
        if section not in allowed:
            unknown.append(section)
            continue
        if section not in normalized:
            normalized.append(section)

    if unknown:
        raise ValueError(  # noqa: TRY003
            f"{path} contains unknown section(s): {', '.join(unknown)}"
        )

    return normalized


def _validate_sqlite_path(value: Path) -> Path:
    if value.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        raise ValueError("cache path must use .sqlite, .sqlite3, or .db")  # noqa: TRY003

    return value


SQLitePath = Annotated[Path, AfterValidator(_validate_sqlite_path)]


def _normalize_int_mapping(value: object) -> object:
    if value is None:
        return {}
    if not isinstance(value, dict):
        return value
    return {str(key).strip(): int(number) for key, number in value.items()}


class PlayerBindingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: SQLitePath = Path("data/seer/player_bindings.sqlite")


class PlayerQueryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_seconds: float = Field(default=30, gt=0)
    detail_timeout_seconds: float = Field(default=90, gt=0)
    sections: list[str] = Field(default_factory=lambda: list(PLAYER_SECTION_KEYS))
    binding: PlayerBindingConfig = Field(default_factory=PlayerBindingConfig)

    @field_validator("sections", mode="before")
    @classmethod
    def coerce_sections(cls, value: object) -> object:
        return _coerce_sections(value)

    @field_validator("sections")
    @classmethod
    def normalize_sections(cls, value: list[str]) -> list[str]:
        return _normalize_sections(
            value,
            PLAYER_SECTION_KEYS,
            path="seer.player.sections",
        )


class TeamQueryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_seconds: float = Field(default=20, gt=0)
    sections: list[str] = Field(default_factory=lambda: ["basic", "resource"])

    @field_validator("sections", mode="before")
    @classmethod
    def coerce_sections(cls, value: object) -> object:
        return _coerce_sections(value)

    @field_validator("sections")
    @classmethod
    def normalize_sections(cls, value: list[str]) -> list[str]:
        return _normalize_sections(
            value,
            TEAM_SECTION_KEYS,
            path="seer.team.sections",
        )


class MintmarkQueryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merge_connected: bool = True


class RankPageRefreshConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    target_limit: int = Field(default=50000, ge=1)
    target_limits: dict[str, int] = Field(default_factory=dict)
    score_cutoffs: dict[str, int] = Field(
        default_factory=lambda: {"群星牌": 1000},
    )
    stale_age_weight: float = Field(default=0.08, ge=0)
    stale_age_max_multiplier: float = Field(default=5.0, ge=1)
    page_size: int = Field(default=100, ge=1)
    pages_per_run: int = Field(default=10, ge=1)
    pages_per_run_min: int = Field(default=0, ge=0)
    interval_minutes: int = Field(default=0, ge=0, le=59)
    interval_offset_minutes: int = Field(default=0, ge=0, le=59)
    schedule_jitter_seconds: int = Field(default=0, ge=0)
    request_interval_seconds: float = Field(default=0.0, ge=0)
    request_jitter_seconds: float = Field(default=0.0, ge=0)
    active_start: str = ""
    active_end: str = ""
    times: list[str] = Field(
        default_factory=lambda: list(DEFAULT_RANK_PAGE_REFRESH_TIMES)
    )
    rank_keys: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_RANK_PAGE_REFRESH_KEYS)
    )
    refresh_stale_after_hours: int = Field(default=24, ge=0)

    @field_validator("times", mode="before")
    @classmethod
    def normalize_times(cls, value: object) -> object:
        return normalized_daily_times(
            value,
            error_message=RANK_PAGE_REFRESH_TIME_ERROR,
        )

    @field_validator("active_start", "active_end", mode="before")
    @classmethod
    def normalize_active_time(cls, value: object) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        return normalized_daily_times(
            [text],
            error_message=RANK_PAGE_REFRESH_ACTIVE_TIME_ERROR,
        )[0]

    @field_validator("target_limits", mode="before")
    @classmethod
    def normalize_target_limits(cls, value: object) -> object:
        return _normalize_int_mapping(value)

    @field_validator("target_limits")
    @classmethod
    def validate_target_limits(cls, value: dict[str, int]) -> dict[str, int]:
        return {key: limit for key, limit in value.items() if key and limit >= 1}

    @field_validator("score_cutoffs", mode="before")
    @classmethod
    def normalize_score_cutoffs(cls, value: object) -> object:
        return _normalize_int_mapping(value)

    @field_validator("score_cutoffs")
    @classmethod
    def validate_score_cutoffs(cls, value: dict[str, int]) -> dict[str, int]:
        return {key: score for key, score in value.items() if key and score >= 1}

    @model_validator(mode="after")
    def validate_interval_offset(self) -> RankPageRefreshConfig:
        if (
            self.interval_minutes > 0
            and self.interval_offset_minutes >= self.interval_minutes
        ):
            raise ValueError(RANK_PAGE_REFRESH_INTERVAL_OFFSET_ERROR)
        if self.pages_per_run_min > self.pages_per_run:
            raise ValueError(RANK_PAGE_REFRESH_PAGES_PER_RUN_MIN_ERROR)
        if bool(self.active_start) != bool(self.active_end):
            raise ValueError(RANK_PAGE_REFRESH_ACTIVE_PAIR_ERROR)
        return self


class RankQueryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10000, ge=0)
    online_limit: int = Field(default=2000, ge=0)
    page_size: int = Field(default=100, ge=1)
    display_limit: int = Field(default=10, ge=1, le=MAX_RANK_DISPLAY_LIMIT)
    max_display_limit: int = Field(
        default=MAX_RANK_DISPLAY_LIMIT,
        ge=1,
        le=MAX_RANK_DISPLAY_LIMIT,
    )
    display_limits: dict[str, int] = Field(default_factory=dict)
    display_limit_path: SQLitePath = Path("data/seer/rank_display_limits.sqlite")
    page_cache: bool = True
    page_cache_ttl_seconds: int = Field(default=3600, ge=0)
    allow_stale_cache: bool = True
    score_search_probe_limit: int = Field(default=32, ge=1)
    score_search_tie_page_limit: int = Field(default=5, ge=1)
    page_cache_path: SQLitePath = Path("data/seer/rank_page_cache.sqlite")
    peak_subkey: int | None = Field(default=None, ge=0)
    page_refresh: RankPageRefreshConfig = Field(
        default_factory=RankPageRefreshConfig
    )

    @field_validator("peak_subkey", mode="before")
    @classmethod
    def empty_peak_subkey_as_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("display_limits", mode="before")
    @classmethod
    def normalize_display_limits(cls, value: object) -> object:
        return _normalize_int_mapping(value)

    @field_validator("display_limits")
    @classmethod
    def validate_display_limits(cls, value: dict[str, int]) -> dict[str, int]:
        return {
            key: limit
            for key, limit in value.items()
            if key and 1 <= limit <= MAX_RANK_DISPLAY_LIMIT
        }

    @model_validator(mode="after")
    def validate_display_limit_bounds(self) -> "RankQueryConfig":
        self.display_limit = min(self.display_limit, self.max_display_limit)
        self.display_limits = {
            key: min(limit, self.max_display_limit)
            for key, limit in self.display_limits.items()
        }
        return self

class LocalRankConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_players: int = Field(default=5000, ge=1)
    batch_limit: int = Field(default=100, ge=1)
    auto_refresh: bool = True
    refresh_hour: int = Field(default=3, ge=0, le=23)
    refresh_minute: int = Field(default=30, ge=0, le=59)
    refresh_limit: int = Field(default=300, ge=1)
    refresh_max_age_hours: int = Field(default=24, ge=0)
    refresh_interval_seconds: float = Field(default=0.5, ge=0)
    path: SQLitePath = Path("data/seer/player_query_cache.sqlite")


class TeamResourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    times: list[str] = Field(default_factory=list)
    commands: NormalizedStringList = Field(default_factory=lambda: ["战队"])
    subscription_path: SQLitePath = Path(
        "data/seer/team_resource_subscriptions.sqlite"
    )
    default_threshold: int = Field(default=1000, ge=0)
    default_at_users: NormalizedStringList = Field(default_factory=list)
    query_timeout_seconds: int = Field(default=20, gt=0)
    resource_line: str = (
        "查到了战队 {team_name}（{team_id}）资源是 {resource}，低于阈值 {threshold}。"
    )
    resource_message: str = "出来买资源，别逼我求你😡"

    @field_validator("times", mode="before")
    @classmethod
    def normalize_times(cls, value: object) -> object:
        return normalized_daily_times(value, error_message=TEAM_RESOURCE_TIME_ERROR)

class RenderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cache_max_size_mb: int = Field(default=200, gt=0)


class SeasonCountdownConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    autocard_name: str = "群星牌赛季"
    autocard_start_time: object | None = None
    autocard_end_time: object | None = None

    @field_validator("autocard_start_time", "autocard_end_time", mode="before")
    @classmethod
    def empty_time_as_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        from datetime import datetime

        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise ValueError("season time must be an ISO datetime")  # noqa: TRY003


class SeerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player: PlayerQueryConfig = Field(default_factory=PlayerQueryConfig)
    team: TeamQueryConfig = Field(default_factory=TeamQueryConfig)
    mintmark: MintmarkQueryConfig = Field(default_factory=MintmarkQueryConfig)
    rank: RankQueryConfig = Field(default_factory=RankQueryConfig)
    local_rank: LocalRankConfig = Field(default_factory=LocalRankConfig)
    team_resource: TeamResourceConfig = Field(default_factory=TeamResourceConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    season: SeasonCountdownConfig = Field(default_factory=SeasonCountdownConfig)
