# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ironsbot.services.seer import local_rank_formatting
from ironsbot.services.seer.local_rank_cache_storage import (
    connect_local_rank_cache,
    max_cached_players,
)
from ironsbot.services.seer.local_rank_metrics import LOCAL_METRICS
from ironsbot.services.seer.local_rank_models import (
    LocalRankCacheStats,
    LocalRankEntry,
)
from ironsbot.services.seer.rank import is_pet_kind_rank_anomaly_user

if TYPE_CHECKING:
    import sqlite3


def get_metric_params(
    metric_key: str,
    season_sub_key: int | None,
) -> tuple[object, object, object]:
    return metric_key, season_sub_key, season_sub_key


def count_metric_rows(
    conn: sqlite3.Connection,
    metric_key: str,
    season_sub_key: int | None,
) -> int:
    params = get_metric_params(metric_key, season_sub_key)
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM metrics m
            JOIN players p ON p.user_id = m.user_id
            WHERE m.metric_key = ?
              AND m.value IS NOT NULL
              AND ((? IS NULL AND m.season_sub_key IS NULL)
                   OR m.season_sub_key = ?)
              AND p.sample_enabled = 1
            """,
            params,
        ).fetchone()[0]
    )


def get_local_rank_entries_sql(
    metric_key: str,
    *,
    limit: int,
    start_rank: int,
    season_sub_key: int | None,
) -> tuple[list[LocalRankEntry], int]:
    requested_limit = max(0, limit)
    safe_start_rank = max(1, start_rank)
    fetch_limit = safe_start_rank + requested_limit - 1
    params = get_metric_params(metric_key, season_sub_key)
    with connect_local_rank_cache() as conn:
        sample_count = count_metric_rows(conn, metric_key, season_sub_key)
        rows = conn.execute(
            """
            SELECT m.value, p.user_id, p.nick, m.display
            FROM metrics m
            JOIN players p ON p.user_id = m.user_id
            WHERE m.metric_key = ?
              AND m.value IS NOT NULL
              AND ((? IS NULL AND m.season_sub_key IS NULL)
                   OR m.season_sub_key = ?)
              AND p.sample_enabled = 1
            ORDER BY m.value DESC, p.user_id ASC
            LIMIT ?
            """,
            (*params, fetch_limit),
        ).fetchall()

        entries: list[LocalRankEntry] = []
        last_value: int | None = None
        current_rank = 0
        for index, row in enumerate(rows, 1):
            value = int(row["value"])
            if value != last_value:
                current_rank = index
                last_value = value

            entries.append(
                LocalRankEntry(
                    rank=current_rank,
                    user_id=int(row["user_id"]),
                    nick=str(row["nick"] or ""),
                    value=value,
                    display=local_rank_formatting.format_metric_display(
                        metric_key,
                        value,
                        row["display"],
                    ),
                )
            )

        start_index = safe_start_rank - 1
        return entries[start_index : start_index + requested_limit], sample_count


def get_cached_player_ids_sql() -> list[int]:
    with connect_local_rank_cache() as conn:
        rows = conn.execute(
            """
            SELECT user_id
            FROM players
            WHERE sample_enabled = 1
            ORDER BY user_id
            """
        ).fetchall()
    return [int(row["user_id"]) for row in rows]


def get_refresh_candidate_player_ids_sql(
    *,
    limit: int,
    max_age_hours: int,
) -> list[int]:
    cutoff: str | None = None
    if max_age_hours > 0:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        ).isoformat()

    with connect_local_rank_cache() as conn:
        rows = conn.execute(
            """
            SELECT user_id
            FROM players
            WHERE sample_enabled = 1
              AND (? IS NULL OR updated_at <= ?)
            ORDER BY updated_at ASC, user_id ASC
            LIMIT ?
            """,
            (cutoff, cutoff, max(0, limit)),
        ).fetchall()
    return [int(row["user_id"]) for row in rows]


def get_local_rank_cache_stats_sql() -> LocalRankCacheStats:
    with connect_local_rank_cache() as conn:
        total_player_count = int(
            conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        )
        player_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM players WHERE sample_enabled = 1"
            ).fetchone()[0]
        )
        metric_counts = {
            spec.title: count_metric_rows(conn, spec.key, None)
            for spec in LOCAL_METRICS
            if not spec.season_limited
        }
        for spec in LOCAL_METRICS:
            if spec.season_limited:
                metric_counts[spec.title] = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) FROM metrics
                        WHERE metric_key = ?
                          AND value IS NOT NULL
                          AND season_sub_key IS NOT NULL
                        """,
                        (spec.key,),
                    ).fetchone()[0]
                )

    return LocalRankCacheStats(
        player_count=player_count,
        total_player_count=total_player_count,
        max_players=max_cached_players(),
        metric_counts=metric_counts,
    )


def can_cache_player_id_sql(player_id: int) -> bool:
    if is_pet_kind_rank_anomaly_user(player_id):
        return False

    with connect_local_rank_cache() as conn:
        row = conn.execute(
            "SELECT sample_enabled FROM players WHERE user_id = ?",
            (player_id,),
        ).fetchone()
        if row is not None and int(row["sample_enabled"]) == 1:
            return True

        player_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM players WHERE sample_enabled = 1"
            ).fetchone()[0]
        )
        return player_count < max_cached_players()


__all__ = [
    "can_cache_player_id_sql",
    "count_metric_rows",
    "get_cached_player_ids_sql",
    "get_local_rank_cache_stats_sql",
    "get_local_rank_entries_sql",
    "get_refresh_candidate_player_ids_sql",
]
