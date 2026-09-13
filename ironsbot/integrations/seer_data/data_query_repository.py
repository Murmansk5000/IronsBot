# SPDX-License-Identifier: MIT
"""Read small query facts from one validated Seer publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from seerapi_models import ApiMetadataORM
from sqlmodel import select

from ironsbot.integrations.seer_data.season_repository import (
    load_peak_season_times,
)
from ironsbot.integrations.seer_data.weekly_preview_repository import (
    load_weekly_preview_links,
)
from ironsbot.services.seer.data_query_facts import WeeklyPreviewLinks

if TYPE_CHECKING:
    from datetime import datetime

    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataReader
    from ironsbot.services.seer.data_query_facts import PeakSeasonTimes


@dataclass(frozen=True, slots=True)
class PublishedDataQueryRepository:
    data: SeerDataReader

    def weekly_preview_links(self) -> WeeklyPreviewLinks:
        with self.data.query(load_weekly_preview_links) as links:
            return WeeklyPreviewLinks(*links)

    def generated_at(self) -> datetime | None:
        with self.data.query(_load_data_generated_at) as generated_at:
            return generated_at

    def peak_season_times(self) -> PeakSeasonTimes | None:
        with self.data.query(load_peak_season_times) as times:
            return times


def _load_data_generated_at(session: Session) -> datetime | None:
    metadata = session.exec(select(ApiMetadataORM)).first()
    return None if metadata is None else metadata.generate_time
