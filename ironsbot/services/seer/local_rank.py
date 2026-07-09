# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ironsbot.config import get_app_config
from ironsbot.config.models.seer import LocalRankConfig
from ironsbot.services.seer import local_rank_formatting
from ironsbot.services.seer.local_rank_cache_storage import (
    connect_local_rank_cache as _connect_cache,
)
from ironsbot.services.seer.local_rank_cache_storage import (
    max_cached_players as _max_cached_players,
)
from ironsbot.services.seer.local_rank_cache_storage import (
    write_player_metrics as _write_player_metrics,
)
from ironsbot.services.seer.local_rank_metrics import (
    LOCAL_METRICS as _LOCAL_METRICS,
)
from ironsbot.services.seer.local_rank_metrics import (
    MetricValue,
)
from ironsbot.services.seer.local_rank_metrics import (
    collect_metrics as _collect_metrics,
)
from ironsbot.services.seer.local_rank_metrics import (
    positive_int as _positive_int,
)
from ironsbot.services.seer.rank import (
    PlayerRankSummary,
    RankLookupResult,
    is_pet_kind_rank_anomaly_user,
)
from ironsbot.services.seer.sequ_extra import UnityPartOneInfo, UnityPeakInfo

_CACHE_LOCK = asyncio.Lock()


def get_local_rank_config() -> LocalRankConfig:
    return get_app_config().seer.local_rank


@dataclass(slots=True)
class LocalRankSummary:
    text: str = ""
    sample_ranks: dict[str, str] = field(default_factory=dict)

    def sample_rank(self, metric_key: str) -> str:
        return self.sample_ranks.get(metric_key, "")


@dataclass(frozen=True, slots=True)
class LocalRankEntry:
    rank: int
    user_id: int
    nick: str
    value: int
    display: str


@dataclass(frozen=True, slots=True)
class LocalRankCacheStats:
    player_count: int
    total_player_count: int
    max_players: int
    metric_counts: dict[str, int]


def _format_peak_rating_score(value: int) -> str:
    return local_rank_formatting.format_peak_rating_score(value)


def _format_metric_display(
    metric_key: str,
    value: int,
    display: object | None = None,
) -> str:
    return local_rank_formatting.format_metric_display(metric_key, value, display)


def _format_percent(value: float) -> str:
    return local_rank_formatting.format_percent(value)


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
    percent_text = _format_percent(rank / sample_count * 100)
    sample_rank_text = f"样本前{percent_text}%"
    tie_text = f"，并列 {tie_count} 人" if tie_count > 1 else ""
    display_text = _format_metric_display(metric_key, current_value, display_value)

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
    for spec in _LOCAL_METRICS:
        metric = current_metrics.get(spec.key)
        if metric is None:
            continue

        value = _positive_int(metric.get("value"))
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


def _get_metric_params(
    metric_key: str,
    season_sub_key: int | None,
) -> tuple[object, object, object]:
    return metric_key, season_sub_key, season_sub_key


def _count_metric_rows(
    conn: sqlite3.Connection,
    metric_key: str,
    season_sub_key: int | None,
) -> int:
    params = _get_metric_params(metric_key, season_sub_key)
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


def _get_local_rank_entries_sql(
    metric_key: str,
    *,
    limit: int,
    start_rank: int,
    season_sub_key: int | None,
) -> tuple[list[LocalRankEntry], int]:
    requested_limit = max(0, limit)
    safe_start_rank = max(1, start_rank)
    fetch_limit = safe_start_rank + requested_limit - 1
    params = _get_metric_params(metric_key, season_sub_key)
    with _connect_cache() as conn:
        sample_count = _count_metric_rows(conn, metric_key, season_sub_key)
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
                    display=_format_metric_display(
                        metric_key,
                        value,
                        row["display"],
                    ),
                )
            )

        start_index = safe_start_rank - 1
        return entries[start_index : start_index + requested_limit], sample_count


def _get_cached_player_ids_sql() -> list[int]:
    with _connect_cache() as conn:
        rows = conn.execute(
            """
            SELECT user_id
            FROM players
            WHERE sample_enabled = 1
            ORDER BY user_id
            """
        ).fetchall()
    return [int(row["user_id"]) for row in rows]


def _get_refresh_candidate_player_ids_sql(
    *,
    limit: int,
    max_age_hours: int,
) -> list[int]:
    cutoff: str | None = None
    if max_age_hours > 0:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        ).isoformat()

    with _connect_cache() as conn:
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


def _get_local_rank_cache_stats_sql() -> LocalRankCacheStats:
    with _connect_cache() as conn:
        total_player_count = int(
            conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        )
        player_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM players WHERE sample_enabled = 1"
            ).fetchone()[0]
        )
        metric_counts = {
            spec.title: _count_metric_rows(conn, spec.key, None)
            for spec in _LOCAL_METRICS
            if not spec.season_limited
        }
        for spec in _LOCAL_METRICS:
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
        max_players=_max_cached_players(),
        metric_counts=metric_counts,
    )


def _can_cache_player_id_sql(player_id: int) -> bool:
    if is_pet_kind_rank_anomaly_user(player_id):
        return False

    with _connect_cache() as conn:
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
        return player_count < _max_cached_players()


async def _upsert_local_rank_metrics_sql(
    *,
    player_id: int,
    nick: str,
    current_metrics: dict[str, MetricValue],
    peak_sub_key: int | None,
) -> LocalRankSummary:
    async with _CACHE_LOCK:
        with _connect_cache() as conn:
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
            if not is_sampled and player_count >= _max_cached_players():
                return _format_summary(
                    conn=conn,
                    current_metrics=current_metrics,
                    peak_sub_key=peak_sub_key,
                    include_current_record=True,
                )

            _write_player_metrics(
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


def get_local_rank_entries(
    metric_key: str,
    *,
    limit: int = 20,
    start_rank: int = 1,
    season_sub_key: int | None = None,
) -> tuple[list[LocalRankEntry], int]:
    return _get_local_rank_entries_sql(
        metric_key,
        limit=limit,
        start_rank=start_rank,
        season_sub_key=season_sub_key,
    )


def get_cached_player_ids() -> list[int]:
    return _get_cached_player_ids_sql()


def get_refresh_candidate_player_ids(
    *,
    limit: int,
    max_age_hours: int,
) -> list[int]:
    return _get_refresh_candidate_player_ids_sql(
        limit=limit,
        max_age_hours=max_age_hours,
    )


def get_local_rank_cache_stats() -> LocalRankCacheStats:
    return _get_local_rank_cache_stats_sql()


def can_cache_player_id(player_id: int) -> bool:
    return _can_cache_player_id_sql(player_id)


async def upsert_local_rank_metrics(
    *,
    player_id: int,
    nick: str,
    current_metrics: dict[str, MetricValue],
    peak_sub_key: int | None,
) -> LocalRankSummary:
    return await _upsert_local_rank_metrics_sql(
        player_id=player_id,
        nick=nick,
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
    current_metrics = _collect_metrics(
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
