# SPDX-License-Identifier: GPL-3.0-or-later
"""Read optional official season windows from the Seer data database."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class PeakSeasonTimes:
    start_time: datetime | None
    end_time: datetime | None


def load_peak_season_times(session: Any) -> PeakSeasonTimes | None:
    """Return the current peak-season timestamps when the data model provides it."""

    try:
        from seerapi_models import PeakSeasonORM
    except ImportError:
        return None

    season = session.get(PeakSeasonORM, 1)
    if season is None:
        return None
    return PeakSeasonTimes(
        start_time=cast("datetime | None", season.start_time),
        end_time=cast("datetime | None", season.end_time),
    )
