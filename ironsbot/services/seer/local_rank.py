# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.services.seer import local_rank_formatting
from ironsbot.services.seer.local_rank_metrics import (
    LOCAL_METRICS,
    MetricValue,
    collect_metrics,
)
from ironsbot.services.seer.local_rank_models import (
    LocalRankCacheStats,
    LocalRankEntry,
    LocalRankSummary,
)
from ironsbot.services.seer.rank_constants import is_pet_kind_rank_anomaly_user
from ironsbot.services.seer.rank_peak import (
    build_peak_rating_score,
)
from ironsbot.services.seer.sequ_extra import (
    UnityPartOneInfo,
    UnityPeakInfo,
    fetch_unity_part_one,
    fetch_unity_peak,
)
from ironsbot.services.seer.value_coercion import coerce_positive_int

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ironsbot.config.models.seer import LocalRankConfig, PlayerQueryConfig
    from ironsbot.services.operations.headless import HeadlessGame
    from ironsbot.services.seer.local_rank_metrics import MetricSpec
    from ironsbot.services.seer.rank import RankService
    from ironsbot.services.seer.rank_models import PlayerRankSummary, RankLookupResult

LocalRankRecord = tuple[int, int, str, int, str]


class LocalRankRepository(Protocol):
    max_players: int

    def entries(
        self,
        metric_key: str,
        *,
        limit: int,
        start_rank: int,
        season_sub_key: int | None,
    ) -> tuple[list[LocalRankRecord], int]: ...

    def refresh_candidate_ids(
        self,
        *,
        limit: int,
        max_age_hours: int,
    ) -> list[int]: ...

    def stats(self, metrics: Sequence[MetricSpec]) -> LocalRankCacheStats: ...

    def can_cache(self, player_id: int) -> bool: ...

    def delete_player(self, player_id: int) -> None: ...

    def upsert_metrics(
        self,
        *,
        player_id: int,
        nick: str,
        metrics: Mapping[str, MetricValue],
        clear_metric_keys: frozenset[str],
        standing_inputs: Mapping[str, tuple[int, int | None]],
    ) -> dict[str, tuple[int, int, int]]: ...


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


@dataclass(slots=True)
class LocalRankService:
    repository: LocalRankRepository
    config: LocalRankConfig
    player_config: PlayerQueryConfig
    rank: RankService
    _write_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def entries(
        self,
        metric_key: str,
        *,
        limit: int,
        start_rank: int,
        season_sub_key: int | None,
    ) -> tuple[list[LocalRankEntry], int]:
        records, sample_count = self.repository.entries(
            metric_key,
            limit=limit,
            start_rank=start_rank,
            season_sub_key=season_sub_key,
        )
        return (
            [
                LocalRankEntry(
                    rank=rank,
                    user_id=user_id,
                    nick=nick,
                    value=value,
                    display=local_rank_formatting.format_metric_display(
                        metric_key,
                        value,
                        display,
                    ),
                )
                for rank, user_id, nick, value, display in records
            ],
            sample_count,
        )

    def stats(self) -> LocalRankCacheStats:
        return self.repository.stats(LOCAL_METRICS)

    def can_cache(self, player_id: int) -> bool:
        return not is_pet_kind_rank_anomaly_user(
            player_id
        ) and self.repository.can_cache(player_id)

    async def upsert_metrics(
        self,
        *,
        player_id: int,
        nick: str,
        current_metrics: Mapping[str, MetricValue],
        peak_sub_key: int | None,
        clear_metric_keys: frozenset[str] = frozenset(),
    ) -> LocalRankSummary:
        async with self._write_lock:
            if is_pet_kind_rank_anomaly_user(player_id):
                self.repository.delete_player(player_id)
                return LocalRankSummary()

            standing_inputs = {
                spec.key: (
                    value,
                    peak_sub_key if spec.season_limited else None,
                )
                for spec in LOCAL_METRICS
                if (metric := current_metrics.get(spec.key)) is not None
                and (value := coerce_positive_int(metric.get("value"))) is not None
            }
            standings = self.repository.upsert_metrics(
                player_id=player_id,
                nick=nick,
                metrics=current_metrics,
                clear_metric_keys=clear_metric_keys,
                standing_inputs=standing_inputs,
            )
        return self._format_summary(
            current_metrics,
            standings,
            peak_sub_key=peak_sub_key,
        )

    async def update_cache(  # noqa: PLR0913
        self,
        *,
        player_id: int,
        nick: str,
        more_info: Any,
        unity_part_one: UnityPartOneInfo,
        unity_peak: UnityPeakInfo,
        rank_summary: PlayerRankSummary,
        autocard_rank_summary: RankLookupResult | None = None,
        peak_sub_key: int | None,
        peak_standard_score: int | None,
        peak_wild_score: int | None,
        peak_expert_score: int | None,
        clear_metric_keys: frozenset[str] = frozenset(),
    ) -> LocalRankSummary:
        current_metrics = collect_metrics(
            more_info=more_info,
            unity_part_one=unity_part_one,
            unity_peak=unity_peak,
            rank_summary=rank_summary,
            autocard_rank_summary=autocard_rank_summary,
            peak_sub_key=peak_sub_key,
            peak_standard_score=peak_standard_score,
            peak_wild_score=peak_wild_score,
            peak_expert_score=peak_expert_score,
        )
        for metric_key in clear_metric_keys:
            current_metrics.pop(metric_key, None)
        return await self.upsert_metrics(
            player_id=player_id,
            nick=nick,
            current_metrics=current_metrics,
            peak_sub_key=peak_sub_key,
            clear_metric_keys=clear_metric_keys,
        )

    async def refresh(
        self,
        game: HeadlessGame,
        player_ids: Sequence[int] | None = None,
    ) -> LocalRankRefreshResult:
        if player_ids is None:
            player_ids = self.repository.refresh_candidate_ids(
                limit=self.config.refresh_limit,
                max_age_hours=self.config.refresh_max_age_hours,
            )
        else:
            player_ids = list(dict.fromkeys(player_ids))
        result = LocalRankRefreshResult(total=len(player_ids))
        if not player_ids:
            return result

        peak_sub_key = self.rank.current_peak_sub_key()
        for player_id in player_ids:
            if not self.can_cache(player_id):
                result.skipped_full += 1
                continue
            try:
                with game.operations.track(
                    "本地样本刷新",
                    f"米米号 {player_id}",
                    source="本地样本刷新",
                    background=True,
                ):
                    await asyncio.wait_for(
                        self._refresh_one(
                            game=game,
                            peak_sub_key=peak_sub_key,
                            player_id=player_id,
                        ),
                        timeout=self.player_config.detail_timeout_seconds,
                    )
            except asyncio.TimeoutError:
                result.failures.append(
                    LocalRankRefreshFailure(player_id, "查询超时")
                )
            except Exception as error:  # noqa: BLE001
                result.failures.append(
                    LocalRankRefreshFailure(player_id, str(error))
                )
            else:
                result.success += 1
            await asyncio.sleep(self.config.refresh_interval_seconds)
        return result

    async def _refresh_one(
        self,
        *,
        game: HeadlessGame,
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
        rank_summary = await self.rank.fetch_player_summary(
            game,
            player_id,
            achieve_score=getattr(more_info, "total_achieve", None),
            pet_kind_count=unity_part_one.pet_kind_num,
            skin_score=unity_part_one.skin_num,
        )
        await self.update_cache(
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

    @staticmethod
    def _format_summary(
        current_metrics: Mapping[str, MetricValue],
        standings: Mapping[str, tuple[int, int, int]],
        *,
        peak_sub_key: int | None,
    ) -> LocalRankSummary:
        lines = ["【机器人查询排行】"]
        sample_ranks: dict[str, str] = {}
        for spec in LOCAL_METRICS:
            metric = current_metrics.get(spec.key)
            standing = standings.get(spec.key)
            if metric is None or standing is None:
                continue
            sample_count, rank, tie_count = standing
            if sample_count <= 0:
                continue
            value = coerce_positive_int(metric.get("value"))
            if value is None:
                continue
            percent_text = local_rank_formatting.format_percent(
                rank / sample_count * 100
            )
            sample_ranks[spec.key] = f"样本前{percent_text}%"
            display_text = local_rank_formatting.format_metric_display(
                spec.key,
                value,
                metric.get("display"),
            )
            tie_text = f"，并列 {tie_count} 人" if tie_count > 1 else ""
            lines.append(
                f"{spec.title}：样本前{percent_text}%"
                f"（{display_text}，样本 {sample_count} 人{tie_text}）"
            )
        if len(lines) == 1:
            lines.append("暂无可比较数据")
        elif peak_sub_key is not None:
            lines.append(f"巅峰赛季样本：{peak_sub_key}")
        return LocalRankSummary(text="\n".join(lines), sample_ranks=sample_ranks)
