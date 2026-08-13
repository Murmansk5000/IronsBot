# SPDX-License-Identifier: MIT
from __future__ import annotations

from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ironsbot.core.time import normalize_daily_time_with_seconds

LUCKY_SKIN_WINDOW_WATCHED_SKIN_IDS_ERROR = (
    "seer.lucky_skin_window watched_skin_ids must be positive"
)
LUCKY_SKIN_WINDOW_TIME_ERROR = "lucky skin time must use HH:MM or HH:MM:SS"


class LuckySkinWindowAccountConfig(BaseModel):
    """One QQ user's account-library subscription for lucky-window checks."""

    model_config = ConfigDict(extra="forbid")

    user: str | int
    account: str | int
    watched_skin_ids: list[int] = Field(default_factory=list)

    @field_validator("watched_skin_ids")
    @classmethod
    def normalize_watched_skin_ids(cls, value: list[int]) -> list[int]:
        if any(skin_id <= 0 for skin_id in value):
            raise ValueError(LUCKY_SKIN_WINDOW_WATCHED_SKIN_IDS_ERROR)
        return list(dict.fromkeys(value))


class LuckySkinWindowConfig(BaseModel):
    """Daily public lucky-window lookup and per-user delivery policy."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    time: str = "00:01:05"
    timezone: str = "Asia/Shanghai"
    timeout_seconds: float = Field(default=15.0, gt=0)
    accounts: list[LuckySkinWindowAccountConfig] = Field(default_factory=list)

    @field_validator("time")
    @classmethod
    def normalize_time(cls, value: str) -> str:
        return normalize_daily_time_with_seconds(
            value,
            error_message=LUCKY_SKIN_WINDOW_TIME_ERROR,
        )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        normalized = value.strip()
        ZoneInfo(normalized)
        return normalized
