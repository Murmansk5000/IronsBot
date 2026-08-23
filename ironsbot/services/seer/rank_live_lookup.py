# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
import time
from functools import partial
from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.rank_constants import (
    EXPERT_PEAK_USER_RANK_KEY,
    STANDARD_PEAK_USER_RANK_KEY,
    WILD_PEAK_USER_RANK_KEY,
)
from ironsbot.services.seer.rank_exclusion_lookups import finalize_visible_lookup
from ironsbot.services.seer.rank_pagination import rank_window_page_starts
from ironsbot.services.seer.rank_position_cache import (
    find_rank_by_cached_position,
    restore_cached_rank_after_timeout,
)
from ironsbot.services.seer.rank_score_lookup import (
    find_rank_by_linear_scan,
    find_rank_by_score,
)
from ironsbot.services.seer.rank_work_cache import save_rank_miss

if TYPE_CHECKING:
    from ironsbot.services.seer.rank_models import RankLookupResult

logger = logging.getLogger(__name__)
_CACHED_LOOKUP_WINDOW_PAGES = 2
_LAST_CONFIRMED_RANK_MAX_AGE_SECONDS = 24 * 60 * 60
_PUBLIC_PEAK_SCORE_KEYS = frozenset(
    (
        STANDARD_PEAK_USER_RANK_KEY,
        WILD_PEAK_USER_RANK_KEY,
        EXPERT_PEAK_USER_RANK_KEY,
    )
)


async def execute_rank_lookup(  # noqa: PLR0913
    service: Any,
    game: Any,
    *,
    user_id: int,
    rank_key: str | None,
    key: int,
    sub_key: int,
    score_target: int | None,
    limit: int,
    page_size: int,
    result: RankLookupResult,
    anchor_only: bool,
    fallback_item: Any | None,
) -> RankLookupResult:
    parallelism = service.rank_probe_parallelism(game)
    batch_enabled = parallelism > 1
    cached_score = (
        None if fallback_item is None else int(fallback_item.score)
    )

    async def fetch_rank_pages(  # noqa: PLR0913
        active_game: Any,
        *,
        key: int,
        sub_key: int,
        starts: tuple[int, ...],
        use_cache: bool = False,
        page_phase: str = "search",
    ) -> list[list[Any]]:
        pages = await service.fetch_page_batch(
            active_game,
            key=key,
            sub_key=sub_key,
            starts=starts,
            use_cache=use_cache,
            page_phase=page_phase,
        )
        return [page.items for page in pages]

    try:
        cached = await find_rank_by_cached_position(
            game,
            user_id=user_id,
            key=key,
            sub_key=sub_key,
            page_size=page_size,
            result=result,
            get_cached_rank_item=partial(
                _recent_confirmed_cache_item,
                service.cache,
                max_age_seconds=_LAST_CONFIRMED_RANK_MAX_AGE_SECONDS,
            ),
            rank_window_page_starts=partial(
                rank_window_page_starts,
                window_pages=_CACHED_LOOKUP_WINDOW_PAGES,
            ),
            fetch_rank_page=service._fetch_page_result_for_position_lookup,
            fetch_rank_pages=(
                service.fetch_page_batch if batch_enabled else None
            ),
            anchor_only=anchor_only,
            parallelism=parallelism,
            recent_cache_max_age_seconds=(
                service.config.player_lookup.recent_cache_max_age_seconds
            ),
            recent_cache_anchor_timeout_seconds=(
                service.config.player_lookup.recent_cache_anchor_timeout_seconds
            ),
        )
        if cached is not None or limit <= 0 or anchor_only:
            result = await finalize_visible_lookup(
                service,
                game,
                rank_key=rank_key,
                key=key,
                sub_key=sub_key,
                result=cached or result,
            )
            _preserve_public_peak_score(
                result,
                key=key,
                score_target=score_target,
            )
            _log_rank_score_mismatch(
                result,
                rank_key=rank_key,
                key=key,
                sub_key=sub_key,
                user_id=user_id,
                expected_score=score_target,
                cached_score=cached_score,
            )
            return result
        if score_target is not None:
            result.cost.used_score_search = True
            result = await find_rank_by_score(
                game,
                user_id=user_id,
                key=key,
                sub_key=sub_key,
                target_score=score_target,
                limit=limit,
                page_size=page_size,
                result=result,
                score_search_probe_limit=service._probe_limit,
                score_search_tie_page_limit=service._tie_page_limit,
                fetch_rank_item=partial(service.fetch_item, page_phase="score_probe"),
                fetch_rank_page=partial(service.fetch_page, page_phase="score_tie"),
                fetch_rank_items=(
                    partial(service.fetch_item_batch, page_phase="score_probe")
                    if batch_enabled
                    else None
                ),
                fetch_rank_pages=fetch_rank_pages if batch_enabled else None,
                parallelism=parallelism,
                allow_nearby_player_lookup=key in _PUBLIC_PEAK_SCORE_KEYS,
            )
        else:
            result.cost.used_full_scan = True
            result = await find_rank_by_linear_scan(
                game,
                user_id=user_id,
                key=key,
                sub_key=sub_key,
                limit=limit,
                page_size=page_size,
                result=result,
                fetch_rank_page=partial(service.fetch_page, page_phase="linear_scan"),
                fetch_rank_pages=fetch_rank_pages if batch_enabled else None,
                parallelism=parallelism,
            )
    except (TimeoutError, asyncio.TimeoutError):
        if fallback_item is not None:
            logger.info(
                "rank lookup timed out; using last confirmed result: "
                "key=%s sub_key=%s user_id=%s rank=%s cached_at=%s",
                key,
                sub_key,
                user_id,
                fallback_item.rank_index + 1,
                fallback_item.fetched_at,
            )
            return restore_cached_rank_after_timeout(result, fallback_item)
        logger.info(
            "rank lookup timed out without a recent confirmed result: "
            "key=%s sub_key=%s user_id=%s",
            key,
            sub_key,
            user_id,
        )
        raise

    result = await finalize_visible_lookup(
        service,
        game,
        rank_key=rank_key,
        key=key,
        sub_key=sub_key,
        result=result,
    )
    _preserve_public_peak_score(
        result,
        key=key,
        score_target=score_target,
    )
    _log_rank_score_mismatch(
        result,
        rank_key=rank_key,
        key=key,
        sub_key=sub_key,
        user_id=user_id,
        expected_score=score_target,
        cached_score=cached_score,
    )
    if (
        score_target is None
        and result.rank is None
        and result.cost.used_full_scan
        and result.failure is None
    ):
        save_rank_miss(
            service.cache,
            key=key,
            sub_key=sub_key,
            user_id=user_id,
            searched_limit=result.searched_limit,
        )
    return result


def _preserve_public_peak_score(
    result: RankLookupResult,
    *,
    key: int,
    score_target: int | None,
) -> None:
    if (
        key in _PUBLIC_PEAK_SCORE_KEYS
        and result.rank is not None
        and score_target is not None
    ):
        result.score = score_target


def _log_rank_score_mismatch(  # noqa: PLR0913 - every field is useful in diagnostics
    result: RankLookupResult,
    *,
    rank_key: str | None,
    key: int,
    sub_key: int,
    user_id: int,
    expected_score: int | None,
    cached_score: int | None,
) -> None:
    reference_source = "public" if expected_score is not None else "cached"
    reference_score = (
        expected_score if expected_score is not None else cached_score
    )
    if (
        result.rank is None
        or reference_score is None
        or result.observed_score is None
        or reference_score == result.observed_score
    ):
        return
    logger.warning(
        "player rank score mismatch: rank_key=%s key=%s sub_key=%s "
        "user_id=%s rank=%s reference=%s reference_score=%s "
        "observed_score=%s",
        rank_key,
        key,
        sub_key,
        user_id,
        result.rank,
        reference_source,
        reference_score,
        result.observed_score,
    )


def _recent_confirmed_cache_item(
    cache: Any,
    *,
    key: int,
    sub_key: int,
    user_id: int,
    max_age_seconds: float,
) -> Any | None:
    """Return a position fact only while it remains eligible as a fallback."""

    cached_item = cache.item(
        key=key,
        sub_key=sub_key,
        user_id=user_id,
        allow_stale=True,
    )
    if cached_item is None:
        return None
    fetched_at = float(getattr(cached_item, "fetched_at", 0.0))
    if time.time() - fetched_at > max_age_seconds:
        return None
    return cached_item
