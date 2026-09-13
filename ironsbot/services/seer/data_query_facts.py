# SPDX-License-Identifier: MIT
"""Published facts required by the small Seer data-query surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class WeeklyPreviewLinks:
    image_url: str
    source_url: str


@dataclass(frozen=True, slots=True)
class PeakSeasonTimes:
    start_time: datetime | None
    end_time: datetime | None


class SeerDataQueryFacts(Protocol):
    def weekly_preview_links(self) -> WeeklyPreviewLinks: ...

    def generated_at(self) -> datetime | None: ...

    def peak_season_times(self) -> PeakSeasonTimes | None: ...
