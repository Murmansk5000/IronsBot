# SPDX-License-Identifier: GPL-3.0-or-later
import json
from collections.abc import Iterable
from pathlib import Path

from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator

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
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return ["all"]

    if text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value

    return [item.strip() for item in text.split(",")]


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


class Config(BaseModel):
    seer_query_rank_limit: int = Field(default=10000, ge=0)
    seer_query_rank_page_size: int = Field(default=100, ge=1)
    seer_query_rank_page_cache: bool = True
    seer_query_rank_page_cache_ttl_seconds: int = Field(default=3600, ge=0)
    seer_query_rank_page_cache_path: Path = Path(
        "data/custom_get_seer_info/rank_page_cache.sqlite"
    )
    seer_query_peak_subkey: int | None = Field(default=None, ge=0)
    seer_query_local_rank: bool = True
    seer_query_local_rank_max_players: int = Field(default=5000, ge=1)
    seer_query_cache_batch_limit: int = Field(default=100, ge=1)
    seer_query_local_rank_path: Path = Path(
        "data/custom_get_seer_info/player_query_cache.sqlite"
    )
    seer_query_player_sections: list[str] = Field(
        default_factory=lambda: list(PLAYER_SECTION_KEYS)
    )
    seer_query_team_sections: list[str] = Field(
        default_factory=lambda: list(TEAM_SECTION_KEYS)
    )

    @field_validator(
        "seer_query_player_sections",
        "seer_query_team_sections",
        mode="before",
    )
    @classmethod
    def coerce_sections(cls, value: object) -> object:
        return _coerce_sections(value)

    @field_validator("seer_query_peak_subkey", mode="before")
    @classmethod
    def empty_peak_subkey_as_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator(
        "seer_query_rank_page_cache_path",
        "seer_query_local_rank_path",
    )
    @classmethod
    def validate_sqlite_cache_path(cls, value: Path) -> Path:
        return _validate_sqlite_path(value)

    @field_validator("seer_query_player_sections")
    @classmethod
    def normalize_player_sections(cls, value: list[str]) -> list[str]:
        return _normalize_sections(value, PLAYER_SECTION_KEYS)

    @field_validator("seer_query_team_sections")
    @classmethod
    def normalize_team_sections(cls, value: list[str]) -> list[str]:
        return _normalize_sections(value, TEAM_SECTION_KEYS)


plugin_config = get_plugin_config(Config)
