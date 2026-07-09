# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ironsbot.services.seer import local_rank_formatting
from ironsbot.services.seer.local_rank_cache_storage import (
    connect_local_rank_cache,
    max_cached_players,
    write_player_metrics,
)
from ironsbot.services.seer.local_rank_metrics import (
    LOCAL_METRICS,
    MetricValue,
    collect_metrics,
    positive_int,
)
from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.rank_constants import is_pet_kind_rank_anomaly_user

if TYPE_CHECKING:
    import sqlite3

    from ironsbot.services.seer.rank_models import PlayerRankSummary, RankLookupResult
    from ironsbot.services.seer.sequ_extra import UnityPartOneInfo, UnityPeakInfo

_CACHE_LOCK = asyncio.Lock()


def _format_local_rank(  # noqa: PLR0913
    *,
    conn: sqlite3.Connection,
    metric_key: str,
    title: str,
    current_value: int | None,
    display_value: object | None = None,
    season_sub_key: int | None = None,
    include_current_record: bool = False,
) -> tuple[str, str] | None:
    if current_value is None:
        return None

    params: tuple[object, ...] = (metric_key, season_sub_key, season_sub_key)

    sample_count = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM metrics m
            JOIN players p ON p.user_id = m.user_id
            WHERE m.metric_key = ?
              AND m.value IS NOT NULL
              AND p.sample_enabled = 1
              AND ((? IS NULL AND m.season_sub_key IS NULL)
                   OR m.season_sub_key = ?)
            """,
            params,
        ).fetchone()[0]
    )
    greater_count = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM metrics m
            JOIN players p ON p.user_id = m.user_id
            WHERE m.metric_key = ?
              AND m.value IS NOT NULL
              AND p.sample_enabled = 1
              AND ((? IS NULL AND m.season_sub_key IS NULL)
                   OR m.season_sub_key = ?)
              AND m.value > ?
            """,
            (*params, current_value),
        ).fetchone()[0]
    )
    tie_count = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM metrics m
            JOIN players p ON p.user_id = m.user_id
            WHERE m.metric_key = ?
              AND m.value IS NOT NULL
              AND p.sample_enabled = 1
              AND ((? IS NULL AND m.season_sub_key IS NULL)
                   OR m.season_sub_key = ?)
              AND m.value = ?
            """,
            (*params, current_value),
        ).fetchone()[0]
    )

    if include_current_record:
        sample_count += 1
        tie_count += 1

    if sample_count <= 0:
        return None

    rank = 1 + greater_count
    percent_text = local_rank_formatting.format_percent(rank / sample_count * 100)
    sample_rank_text = f"样本前{percent_text}%"
    tie_text = f"，并列 {tie_count} 人" if tie_count > 1 else ""
    display_text = local_rank_formatting.format_metric_display(
        metric_key,
        current_value,
        display_value,
    )

    summary_text = (
        f"{title}：样本前{percent_text}%"
        f"（{display_text}，样本 {sample_count} 人{tie_text}）"
    )
    return summary_text, sample_rank_text


def _format_summary(
    *,
    conn: sqlite3.Connection,
    current_metrics: dict[str, MetricValue],
    peak_sub_key: int | None,
    include_current_record: bool = False,
) -> LocalRankSummary:
    lines = ["【机器人查询排行】"]
    sample_ranks: dict[str, str] = {}
    for spec in LOCAL_METRICS:
        metric = current_metrics.get(spec.key)
        if metric is None:
            continue

        value = positive_int(metric.get("value"))
        season_sub_key = peak_sub_key if spec.season_limited else None
        result = _format_local_rank(
            conn=conn,
            metric_key=spec.key,
            title=spec.title,
            current_value=value,
            display_value=metric.get("display"),
            season_sub_key=season_sub_key,
            include_current_record=include_current_record,
        )
        if result is not None:
            line, rank_text = result
            lines.append(line)
            sample_ranks[spec.key] = rank_text

    if len(lines) == 1:
        lines.append("暂无可比较数据")
    elif peak_sub_key is not None:
        lines.append(f"巅峰赛季样本：{peak_sub_key}")

    return LocalRankSummary(
        text="\n".join(lines),
        sample_ranks=sample_ranks,
    )


async def upsert_local_rank_metrics(
    *,
    player_id: int,
    nick: str,
    current_metrics: dict[str, MetricValue],
    peak_sub_key: int | None,
) -> LocalRankSummary:
    async with _CACHE_LOCK:
        with connect_local_rank_cache() as conn:
            if is_pet_kind_rank_anomaly_user(player_id):
                conn.execute("DELETE FROM metrics WHERE user_id = ?", (player_id,))
                conn.execute("DELETE FROM players WHERE user_id = ?", (player_id,))
                return LocalRankSummary()

            row = conn.execute(
                "SELECT sample_enabled FROM players WHERE user_id = ?",
                (player_id,),
            ).fetchone()
            player_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM players WHERE sample_enabled = 1"
                ).fetchone()[0]
            )
            is_sampled = row is not None and int(row["sample_enabled"]) == 1
            if not is_sampled and player_count >= max_cached_players():
                return _format_summary(
                    conn=conn,
                    current_metrics=current_metrics,
                    peak_sub_key=peak_sub_key,
                    include_current_record=True,
                )

            write_player_metrics(
                conn,
                player_id=player_id,
                nick=nick,
                metrics=current_metrics,
                sample_enabled=True,
            )
            return _format_summary(
                conn=conn,
                current_metrics=current_metrics,
                peak_sub_key=peak_sub_key,
            )


async def update_local_rank_cache(  # noqa: PLR0913
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

    return await upsert_local_rank_metrics(
        player_id=player_id,
        nick=nick,
        current_metrics=current_metrics,
        peak_sub_key=peak_sub_key,
    )
