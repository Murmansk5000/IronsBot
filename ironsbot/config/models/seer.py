# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ironsbot.shared.config.parsing import int_list, string_list

if TYPE_CHECKING:
    from collections.abc import Iterable

PLAYER_SECTION_KEYS: tuple[str, ...] = (
    "basic",
    "appearance",
    "social",
    "collection",
    "rank",
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


class RankQueryConfig(BaseModel):
    limit: int = Field(default=10000, ge=0)
    online_limit: int = Field(default=2000, ge=0)
    page_size: int = Field(default=100, ge=1)
    page_cache: bool = True
    page_cache_ttl_seconds: int = Field(default=3600, ge=0)
    allow_stale_cache: bool = True
    refresh_stale_cache: bool = True
    page_cache_path: Path = Path("data/seer/rank_page_cache.sqlite")
    peak_subkey: int | None = Field(default=None, ge=0)

    @field_validator("peak_subkey", mode="before")
    @classmethod
    def empty_peak_subkey_as_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("page_cache_path")
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
    rank: RankQueryConfig = Field(default_factory=RankQueryConfig)
    local_rank: LocalRankConfig = Field(default_factory=LocalRankConfig)
    team_shortcut: TeamShortcutConfig = Field(default_factory=TeamShortcutConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)


__all__ = [
    "PLAYER_SECTION_KEYS",
    "TEAM_SECTION_KEYS",
    "LocalRankConfig",
    "PlayerQueryConfig",
    "RankQueryConfig",
    "RenderConfig",
    "SeerConfig",
    "TeamConfig",
    "TeamQueryConfig",
    "TeamShortcutConfig",
]
