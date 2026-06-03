# SPDX-License-Identifier: GPL-3.0-or-later
import json
from collections.abc import Iterable

from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator

PLAYER_SECTION_KEYS: tuple[str, ...] = (
    "basic",
    "appearance",
    "social",
    "collection",
    "rank",
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
        raise ValueError(f"unknown sections: {', '.join(unknown)}")

    return normalized


class Config(BaseModel):
    custom_get_seer_info_rank_search_limit: int = Field(default=10000, ge=0)
    custom_get_seer_info_rank_page_size: int = Field(default=100, ge=1)
    custom_get_seer_info_peak_season_sub_key: int | None = Field(default=None, ge=0)
    custom_get_seer_info_player_sections: list[str] = Field(
        default_factory=lambda: list(PLAYER_SECTION_KEYS)
    )
    custom_get_seer_info_team_sections: list[str] = Field(
        default_factory=lambda: list(TEAM_SECTION_KEYS)
    )

    @field_validator(
        "custom_get_seer_info_player_sections",
        "custom_get_seer_info_team_sections",
        mode="before",
    )
    @classmethod
    def coerce_sections(cls, value: object) -> object:
        return _coerce_sections(value)

    @field_validator("custom_get_seer_info_player_sections")
    @classmethod
    def normalize_player_sections(cls, value: list[str]) -> list[str]:
        return _normalize_sections(value, PLAYER_SECTION_KEYS)

    @field_validator("custom_get_seer_info_team_sections")
    @classmethod
    def normalize_team_sections(cls, value: list[str]) -> list[str]:
        return _normalize_sections(value, TEAM_SECTION_KEYS)


plugin_config = get_plugin_config(Config)
