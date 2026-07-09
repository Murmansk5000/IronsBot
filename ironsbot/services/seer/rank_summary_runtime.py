# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.config.loader import get_app_config
from ironsbot.services.seer.rank_lookup_runtime import (
    find_pet_kind_rank,
    find_rank,
    get_current_peak_sub_key,
)
from ironsbot.services.seer.rank_summary import (
    fetch_autocard_rank_summary as fetch_autocard_rank_summary_with_deps,
)
from ironsbot.services.seer.rank_summary import (
    fetch_peak_season_rank_summary as fetch_peak_season_rank_summary_with_deps,
)
from ironsbot.services.seer.rank_summary import (
    fetch_player_rank_summary as fetch_player_rank_summary_with_deps,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.rank_models import (
        PeakSeasonRankSummary,
        PlayerRankSummary,
        RankLookupResult,
    )

BOOK_BREAKDOWN_SCAN_LIMIT = 2_000


async def fetch_peak_season_rank_summary(
    game: Any,
    user_id: int,
    *,
    standard_score: int | None = None,
    wild_score: int | None = None,
    expert_score: int | None = None,
) -> PeakSeasonRankSummary:
    return await fetch_peak_season_rank_summary_with_deps(
        game,
        user_id,
        standard_score=standard_score,
        wild_score=wild_score,
        expert_score=expert_score,
        current_peak_sub_key=get_current_peak_sub_key(),
        find_rank=find_rank,
    )


async def fetch_autocard_rank_summary(
    game: Any,
    user_id: int,
) -> RankLookupResult:
    return await fetch_autocard_rank_summary_with_deps(
        game,
        user_id,
        find_rank=find_rank,
    )


async def fetch_player_rank_summary(  # noqa: PLR0913
    game: Any,
    user_id: int,
    *,
    book_score: int | None = None,
    achieve_score: int | None = None,
    pet_kind_count: int = 0,
    skin_score: int | None = None,
) -> PlayerRankSummary:
    limit = min(
        max(0, get_app_config().seer.rank.limit),
        BOOK_BREAKDOWN_SCAN_LIMIT,
    )
    return await fetch_player_rank_summary_with_deps(
        game,
        user_id,
        book_score=book_score,
        achieve_score=achieve_score,
        pet_kind_count=pet_kind_count,
        skin_score=skin_score,
        book_breakdown_limit=limit,
        find_rank=find_rank,
        find_pet_kind_rank=find_pet_kind_rank,
    )
