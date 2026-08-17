# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import TYPE_CHECKING, Any

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

    async def fetch_rank_pages(
        active_game: Any,
        *,
        key: int,
        sub_key: int,
        starts: tuple[int, ...],
        use_cache: bool = False,
    ) -> list[list[Any]]:
        pages = await service.fetch_page_batch(
            active_game,
            key=key,
            sub_key=sub_key,
            starts=starts,
            use_cache=use_cache,
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
            get_cached_rank_item=partial(service.cache.item, allow_stale=True),
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
        )
        if cached is not None or limit <= 0 or anchor_only:
            return await finalize_visible_lookup(
                service,
                game,
                rank_key=rank_key,
                key=key,
                sub_key=sub_key,
                result=cached or result,
            )
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
                fetch_rank_item=service.fetch_item,
                fetch_rank_page=service.fetch_page,
                fetch_rank_items=(
                    service.fetch_item_batch if batch_enabled else None
                ),
                fetch_rank_pages=fetch_rank_pages if batch_enabled else None,
                parallelism=parallelism,
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
                fetch_rank_page=service.fetch_page,
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
