# SPDX-License-Identifier: MIT
"""Somua lookup composition using the common rank scheduler and caches."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.rank_player_scheduler import PlayerRankLookupJob
from ironsbot.services.seer.somua import (
    SOMUA_RANK_KEY,
    SOMUA_RANK_SUB_KEY,
)
from ironsbot.services.seer.somua_models import SomuaRankEntry

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
    async def operation() -> RankLookupResult:
        result = await service.find_rank(
            game,
            user_id=user_id,
            title="苏摩全服榜",
            score_name="分",
            key=SOMUA_RANK_KEY,
            sub_key=SOMUA_RANK_SUB_KEY,
            target_score=score,
            anchor_only=anchor_only,
        )
        if result.rank is None or result.failure or result.cost.restricted_miss:
            result.common_failure = "尚未定位到可信榜单记录"
            return result
        cached = service.cache.item(
            key=SOMUA_RANK_KEY,
            sub_key=SOMUA_RANK_SUB_KEY,
            user_id=user_id,
            allow_stale=False,
        )
        if (
            cached is not None
            and cached.rank_index + 1 == result.rank
            and cached.score == result.score
            and cached.common_somua is not None
        ):
            result.common_somua = cached.common_somua
            result.common_fetched_at = cached.fetched_at
            return result
        if cached is not None and cached.somua_legacy:
            result.common_failure = "旧版榜单未提供常用苏摩"
            return result
        if anchor_only:
            result.common_failure = "缓存未提供常用苏摩，当前查询额度不允许补查"
            return result
        try:
            offset = result.rank - 1
            page = await service.fetch_page_result(
                game,
                key=SOMUA_RANK_KEY,
                sub_key=SOMUA_RANK_SUB_KEY,
                start=offset,
                end=offset,
                use_cache=False,
            )
            result.record_page(offset, page)
            row = page.items[0] if len(page.items) == 1 else None
            if row is None or row.id != user_id or row.score != result.score:
                result.common_failure = "榜单位置或积分已变化，请重新查询"
                result.failure = result.common_failure
                result.rank = None
            elif isinstance(row, SomuaRankEntry):
                result.common_somua = row.common_somua
                result.common_fetched_at = page.fetched_at
            else:
                result.common_failure = "旧版榜单未提供常用苏摩"
        except Exception as error:  # noqa: BLE001 - independent optional field failure
            result.common_failure = f"常用苏摩补查失败：{type(error).__name__}"
        return result

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
