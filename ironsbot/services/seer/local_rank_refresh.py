# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from ironsbot.config.loader import get_app_config
from ironsbot.config.models.seer import LocalRankConfig, PlayerQueryConfig
from ironsbot.services.seer.client import get_game_client
from ironsbot.services.seer.local_rank import (
    can_cache_player_id,
    get_refresh_candidate_player_ids,
    update_local_rank_cache,
)
from ironsbot.services.seer.rank import (
    build_peak_rating_score,
    fetch_player_rank_summary,
    get_current_peak_sub_key,
)
from ironsbot.services.seer.sequ_extra import (
    fetch_unity_part_one,
    fetch_unity_peak,
)


class LocalRankGameClient(Protocol):
    async def get_user_info(self, user_id: int) -> Any: ...

    async def get_more_user_info(self, user_id: int) -> Any: ...


@dataclass(slots=True)
class LocalRankRefreshFailure:
    player_id: int
    reason: str


@dataclass(slots=True)
class LocalRankRefreshResult:
    total: int
    success: int = 0
    skipped_full: int = 0
    failures: list[LocalRankRefreshFailure] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return len(self.failures)


def get_local_rank_config() -> LocalRankConfig:
    return get_app_config().seer.local_rank


def get_player_query_config() -> PlayerQueryConfig:
    return get_app_config().seer.player


async def refresh_local_rank_cache(
    player_ids: Sequence[int] | None = None,
) -> LocalRankRefreshResult:
    local_rank_config = get_local_rank_config()
    player_config = get_player_query_config()
    if player_ids is None:
        player_ids = get_refresh_candidate_player_ids(
            limit=local_rank_config.refresh_limit,
            max_age_hours=local_rank_config.refresh_max_age_hours,
        )
    else:
        player_ids = list(dict.fromkeys(player_ids))

    result = LocalRankRefreshResult(total=len(player_ids))
    if not player_ids:
        return result

    game = get_game_client()
    peak_sub_key = get_current_peak_sub_key()

    for player_id in player_ids:
        if not can_cache_player_id(player_id):
            result.skipped_full += 1
            continue

        try:
            await asyncio.wait_for(
                _refresh_one_player(
                    game=game,
                    peak_sub_key=peak_sub_key,
                    player_id=player_id,
                ),
                timeout=player_config.detail_timeout_seconds,
            )
        except asyncio.TimeoutError:
            result.failures.append(
                LocalRankRefreshFailure(
                    player_id=player_id,
                    reason="查询超时",
                )
            )
        except Exception as e:  # noqa: BLE001
            result.failures.append(
                LocalRankRefreshFailure(
                    player_id=player_id,
                    reason=str(e),
                )
            )
        else:
            result.success += 1

        await asyncio.sleep(local_rank_config.refresh_interval_seconds)

    return result


async def _refresh_one_player(
    *,
    game: LocalRankGameClient,
    peak_sub_key: int | None,
    player_id: int,
) -> None:
    user_info, more_info = await asyncio.gather(
        game.get_user_info(player_id),
        game.get_more_user_info(player_id),
    )
    unity_part_one, unity_peak = await asyncio.gather(
        fetch_unity_part_one(game, player_id),
        fetch_unity_peak(game, player_id),
    )
    peak_standard_score = (
        build_peak_rating_score(
            unity_peak.current_j_rank,
            unity_peak.current_j_star,
        )
        if unity_peak.current_j_all > 0
        else None
    )
    peak_wild_score = (
        build_peak_rating_score(
            unity_peak.current_k_rank,
            unity_peak.current_k_star,
        )
        if unity_peak.current_k_all > 0
        else None
    )
    peak_expert_score = (
        unity_peak.current_z_score if unity_peak.current_z_all > 0 else None
    )
    rank_summary = await fetch_player_rank_summary(
        game,
        player_id,
        achieve_score=getattr(more_info, "total_achieve", None),
        pet_kind_count=unity_part_one.pet_kind_num,
        skin_score=unity_part_one.skin_num,
    )
    await update_local_rank_cache(
        player_id=player_id,
        nick=user_info.nick,
        more_info=more_info,
        unity_part_one=unity_part_one,
        unity_peak=unity_peak,
        rank_summary=rank_summary,
        peak_sub_key=peak_sub_key,
        peak_standard_score=peak_standard_score,
        peak_wild_score=peak_wild_score,
        peak_expert_score=peak_expert_score,
    )


def format_refresh_failures(
    failures: list[LocalRankRefreshFailure],
    *,
    limit: int = 5,
) -> list[str]:
    lines = [
        f"- {failure.player_id}: {failure.reason}"
        for failure in failures[:limit]
    ]
    if len(failures) > limit:
        lines.append(f"- 另有 {len(failures) - limit} 个失败，日志里可继续看。")
    return lines
