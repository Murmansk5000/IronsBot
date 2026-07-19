# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ironsbot.core.commands import positive_int_list

DEFAULT_ACTIVITY_MESSAGE = "⏰ 本周活动将在约 {lead_hours} 小时后结束\n{activity_list}"
DEFAULT_ACTIVITY_NOTICE_TIMEOUT_SECONDS = 8.0


class ActivityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    lead_hours: list[int] = Field(default_factory=lambda: [11, 1])
    grace_minutes: int = Field(default=15, ge=1)
    only_shown: bool = True
    cache_path: Path = Path("data/activity_reminder/sent.sqlite")
    message: str = DEFAULT_ACTIVITY_MESSAGE
    notice_timeout_seconds: float = Field(
        default=DEFAULT_ACTIVITY_NOTICE_TIMEOUT_SECONDS,
        gt=0,
    )

    @field_validator("lead_hours", mode="before")
    @classmethod
    def coerce_int_list(cls, value: object) -> object:
        return positive_int_list(value)
