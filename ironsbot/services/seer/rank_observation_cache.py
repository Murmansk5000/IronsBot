# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
from copy import deepcopy
from typing import TYPE_CHECKING

from ironsbot.core.platform import reference_digest
from ironsbot.core.time import now
from ironsbot.services.seer.observation_cache import CachedObservation
from ironsbot.services.seer.rank_models import RankLookupCost

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessGame
    from ironsbot.services.seer.rank import RankService
    from ironsbot.services.seer.rank_models import RankLookupResult

logger = logging.getLogger(__name__)


async def find_confirmed_rank(  # noqa: PLR0913
    service: RankService,
    game: HeadlessGame,
    *,
    user_id: int,
    title: str,
    score_name: str,
    key: int,
    sub_key: int,
    target_score: int | None,
    search_limit: int | None,
    anchor_only: bool,
) -> RankLookupResult:
    rank_key = service.exclusion_policy.rank_key_for_protocol(key=key, sub_key=sub_key)
    # Authorization/exclusion must precede reuse. Scope includes the protocol cycle.
    identity = (user_id, key, sub_key)
    ttl = service.config.player_lookup.recent_cache_max_age_seconds
    cached = service._confirmed.get(identity, ttl)
    if cached is not None and not service.exclusion_policy.excludes_from_public_rank(
        rank_key,
        user_id,
    ):
        result = deepcopy(cached.value)
        score_matches = target_score is None or result.score == target_score
        limit = service._online_search_limit(rank_key, search_limit)
        covers_range = result.rank is not None or result.searched_limit >= limit
        if score_matches and covers_range:
            result.title, result.score_name = title, score_name
            result.cost = RankLookupCost(
                cache_page_hits=1,
                reused_successful_observation=True,
            )
            logger.info(
                "player rank confirmed observation reused: key=%s sub_key=%s "
                "player_ref=%s age=%.3fs",
                key,
                sub_key,
                reference_digest(str(user_id)),
                now().timestamp() - cached.fetched_at,
            )
            return result
        service._confirmed.discard(identity)

    async def load() -> CachedObservation:
        result = await service._find_rank_uncached(
            game,
            user_id=user_id,
            title=title,
            score_name=score_name,
            key=key,
            sub_key=sub_key,
            target_score=target_score,
            search_limit=search_limit,
            anchor_only=anchor_only,
        )
        if (
            result.failure is None
            and not result.cost.restricted_miss
            and not result.excluded
            and result.queried
            and result.fallback_cached_at is None
            and (result.observed_score is None or result.observed_score == result.score)
            and (target_score is None or result.score == target_score)
        ):
            service._confirmed.save(identity, result, result.fetched_at)
        return CachedObservation(result, result.fetched_at or now().timestamp())

    shared_key = (*identity, target_score, search_limit, anchor_only)
    shared = service._confirmed.inflight(shared_key)
    item = await service._confirmed.share(
        shared_key,
        load,
    )
    if shared:
        item.value.cost = RankLookupCost(
            cache_page_hits=1,
            reused_successful_observation=True,
        )
    item.value.title, item.value.score_name = title, score_name
    return item.value
