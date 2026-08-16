# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class ActivityInfo:
    activity_id: int
    name: str
    start_time: datetime | None
    end_time: datetime
    sort_order: int
    offer_label: str | None = None
    offer_window_days: int | None = None
    offer_end_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class ActivityReminder:
    activity_id: int
    name: str
    end_time: datetime
    lead_hours: int
    send_time: datetime
    end_label: str = "结束时间"
    display_end_time: bool = True


@dataclass(frozen=True, slots=True)
class ActivityDeadline:
    end_time: datetime
    label: str
    display_end_time: bool


@dataclass(slots=True)
class ActivityInfoCache:
    items: list[ActivityInfo] = field(default_factory=list)
    expires_at: datetime | None = None
    new_activity_ids: frozenset[int] = frozenset()
    has_previous_week_snapshot: bool = False
