# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ironsbot.shared.config.parsing import int_list, string_list
from ironsbot.shared.config.time import normalized_daily_times

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
    "APP_CONFIG.seer.rank.page_refresh.times must contain daily HH:MM times"
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
)
MAX_RANK_DISPLAY_LIMIT = 100


def _coerce_sections(value: object) -> object:
    if value is None or value == "":
        return ["all"]

    return string_list(value)


def _normalize_sections(value: Iterable[str], allowed: tuple[str, ...]) -> list[str]:
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
        raise ValueError(f"unknown sections: {', '.join(unknown)}")  # noqa: TRY003

    return normalized


def _validate_sqlite_path(value: Path) -> Path:
    if value.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        raise ValueError("cache path must use .sqlite, .sqlite3, or .db")  # noqa: TRY003

    return value


class PlayerQueryConfig(BaseModel):
    rate_limit_seconds: int = Field(default=60, ge=0)
    failure_rate_limit_seconds: int = Field(default=10, ge=0)
    timeout_seconds: float = Field(default=30, gt=0)
    detail_timeout_seconds: float = Field(default=90, gt=0)
    sections: list[str] = Field(default_factory=lambda: list(PLAYER_SECTION_KEYS))

    @field_validator("sections", mode="before")
    @classmethod
    def coerce_sections(cls, value: object) -> object:
        return _coerce_sections(value)

    @field_validator("sections")
    @classmethod
    def normalize_sections(cls, value: list[str]) -> list[str]:
        return _normalize_sections(value, PLAYER_SECTION_KEYS)


class TeamQueryConfig(BaseModel):
    rate_limit_seconds: int = Field(default=60, ge=0)
    failure_rate_limit_seconds: int = Field(default=10, ge=0)
    timeout_seconds: float = Field(default=20, gt=0)
    sections: list[str] = Field(default_factory=lambda: list(TEAM_SECTION_KEYS))

    @field_validator("sections", mode="before")
    @classmethod
    def coerce_sections(cls, value: object) -> object:
        return _coerce_sections(value)

    @field_validator("sections")
    @classmethod
    def normalize_sections(cls, value: list[str]) -> list[str]:
        return _normalize_sections(value, TEAM_SECTION_KEYS)


class MintmarkQueryConfig(BaseModel):
    merge_connected: bool = True


class RankPageRefreshConfig(BaseModel):
    enabled: bool = True
    target_limit: int = Field(default=50000, ge=1)
    target_limits: dict[str, int] = Field(default_factory=dict)
    stale_priority_limit: int = Field(default=2000, ge=0)
    rank_position_weight: float = Field(default=1.0, ge=0)
    rank_position_power: float = Field(default=0.5, ge=0)
    rank_position_max_multiplier: float = Field(default=10.0, ge=1)
    reason_weights: dict[str, float] = Field(default_factory=dict)
    stale_age_weight: float = Field(default=0.2, ge=0)
    stale_age_max_multiplier: float = Field(default=5.0, ge=1)
    page_size: int = Field(default=100, ge=1)
    pages_per_run: int = Field(default=10, ge=1)
    times: list[str] = Field(
        default_factory=lambda: list(DEFAULT_RANK_PAGE_REFRESH_TIMES)
    )
    rank_keys: list[str] = Field(
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

    @field_validator("rank_keys", mode="before")
    @classmethod
    def normalize_rank_keys(cls, value: object) -> object:
        return string_list(value)

    @field_validator("target_limits", mode="before")
    @classmethod
    def normalize_target_limits(cls, value: object) -> object:
        if value is None:
            return {}
        if not isinstance(value, dict):
            return value
        return {str(key).strip(): int(limit) for key, limit in value.items()}

    @field_validator("target_limits")
    @classmethod
    def validate_target_limits(cls, value: dict[str, int]) -> dict[str, int]:
        return {key: limit for key, limit in value.items() if key and limit >= 1}

    @field_validator("reason_weights", mode="before")
    @classmethod
    def normalize_reason_weights(cls, value: object) -> object:
        if value is None:
            return {}
        if not isinstance(value, dict):
            return value
        return {str(key).strip(): float(weight) for key, weight in value.items()}

    @field_validator("reason_weights")
    @classmethod
    def validate_reason_weights(cls, value: dict[str, float]) -> dict[str, float]:
        return {key: weight for key, weight in value.items() if key and weight > 0}


class RankQueryConfig(BaseModel):
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
    display_limit_path: Path = Path("data/seer/rank_display_limits.sqlite")
    page_cache: bool = True
    page_cache_ttl_seconds: int = Field(default=3600, ge=0)
    allow_stale_cache: bool = True
    refresh_stale_cache: bool = True
    page_cache_path: Path = Path("data/seer/rank_page_cache.sqlite")
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
        if value is None:
            return {}
        if not isinstance(value, dict):
            return value
        return {str(key).strip(): int(limit) for key, limit in value.items()}

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

    @field_validator("page_cache_path", "display_limit_path")
    @classmethod
    def validate_sqlite_cache_path(cls, value: Path) -> Path:
        return _validate_sqlite_path(value)


class LocalRankConfig(BaseModel):
    enabled: bool = True
    max_players: int = Field(default=5000, ge=1)
    batch_limit: int = Field(default=100, ge=1)
    auto_refresh: bool = True
    refresh_hour: int = Field(default=3, ge=0, le=23)
    refresh_minute: int = Field(default=30, ge=0, le=59)
    refresh_limit: int = Field(default=300, ge=1)
    refresh_max_age_hours: int = Field(default=24, ge=0)
    refresh_interval_seconds: float = Field(default=0.5, ge=0)
    path: Path = Path("data/seer/player_query_cache.sqlite")

    @field_validator("path")
    @classmethod
    def validate_sqlite_cache_path(cls, value: Path) -> Path:
        return _validate_sqlite_path(value)


class TeamConfig(BaseModel):
    commands: list[str] = Field(default_factory=lambda: ["战队"])
    resource_threshold: int = Field(default=1000, ge=0)
    query_timeout_seconds: int = Field(default=20, gt=0)
    resource_message: str = "出来买资源，别逼我求你😡"

    @field_validator("commands", mode="before")
    @classmethod
    def normalize_commands(cls, value: object) -> object:
        return string_list(value)


class TeamShortcutConfig(TeamConfig):
    team_ids: list[int] = Field(default_factory=list)
    resource_users: list[int] = Field(default_factory=list)

    @field_validator("team_ids", "resource_users", mode="before")
    @classmethod
    def normalize_int_lists(cls, value: object) -> object:
        return int_list(value)


class RenderConfig(BaseModel):
    cache_dir: Path | None = Path("render_cache")
    cache_max_size_mb: int = Field(default=200, gt=0)
    clear_on_startup: bool = True


class SeerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player: PlayerQueryConfig = Field(default_factory=PlayerQueryConfig)
    team: TeamQueryConfig = Field(default_factory=TeamQueryConfig)
    mintmark: MintmarkQueryConfig = Field(default_factory=MintmarkQueryConfig)
    rank: RankQueryConfig = Field(default_factory=RankQueryConfig)
    local_rank: LocalRankConfig = Field(default_factory=LocalRankConfig)
    team_shortcut: TeamShortcutConfig = Field(default_factory=TeamShortcutConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)


__all__ = [
    "PLAYER_SECTION_KEYS",
    "RANK_PAGE_REFRESH_TIME_ERROR",
    "TEAM_SECTION_KEYS",
    "LocalRankConfig",
    "MintmarkQueryConfig",
    "PlayerQueryConfig",
    "RankPageRefreshConfig",
    "RankQueryConfig",
    "RenderConfig",
    "SeerConfig",
    "TeamConfig",
    "TeamQueryConfig",
    "TeamShortcutConfig",
]
