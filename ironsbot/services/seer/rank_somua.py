# SPDX-License-Identifier: MIT
"""Somua lookup composition using the common rank scheduler and caches."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.services.seer.rank_player_scheduler import PlayerRankLookupJob
from ironsbot.services.seer.somua import (
    SOMUA_RANK_KEY,
    SOMUA_RANK_LIMIT,
    SOMUA_RANK_SUB_KEY,
)

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessGame
    from ironsbot.services.seer.rank import RankService
    from ironsbot.services.seer.rank_models import RankLookupResult


async def fetch_somua_rank(
    service: RankService,
    game: HeadlessGame,
    user_id: int,
    *,
    score: int | None,
    anchor_only: bool,
) -> RankLookupResult:
    operation = partial(
        service.find_rank,
        game,
        user_id=user_id,
        title="苏摩全服榜",
        score_name="分",
        key=SOMUA_RANK_KEY,
        sub_key=SOMUA_RANK_SUB_KEY,
        target_score=score,
        search_limit=SOMUA_RANK_LIMIT,
        anchor_only=anchor_only,
    )
    job = PlayerRankLookupJob(
        id="somua",
        title="苏摩全服榜",
        key=SOMUA_RANK_KEY,
        sub_key=SOMUA_RANK_SUB_KEY,
        user_id=user_id,
        target_score=score,
        operation=operation,
    )
    return (await service.run_player_lookup_jobs([job]))["somua"]
