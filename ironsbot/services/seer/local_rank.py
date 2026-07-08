# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from ironsbot.config import get_app_config
from ironsbot.config.models.seer import LocalRankConfig
from ironsbot.services.seer.rank import (
    PlayerRankSummary,
    RankLookupResult,
    is_pet_kind_rank_anomaly_user,
)
from ironsbot.services.seer.sequ_extra import UnityPartOneInfo, UnityPeakInfo

MetricValue = dict[str, int | str | None]


@dataclass(frozen=True, slots=True)
class _MetricSpec:
    key: str
    title: str
    season_limited: bool = False


_LOCAL_METRICS: tuple[_MetricSpec, ...] = (
    _MetricSpec("book_score", "图鉴积分"),
    _MetricSpec("achievement_score", "成就点数"),
    _MetricSpec("achievement_count", "成就数量"),
    _MetricSpec("pet_total_count", "精灵数量"),
    _MetricSpec("pet_kind_count", "精灵图鉴"),
    _MetricSpec("countermark_count", "刻印图鉴"),
    _MetricSpec("outfit_suit_count", "套装图鉴"),
    _MetricSpec("outfit_part_count", "部件图鉴"),
    _MetricSpec("mount_count", "座驾图鉴"),
    _MetricSpec("skin_count", "皮肤图鉴"),
    _MetricSpec("autocard_score", "群星牌积分"),
    _MetricSpec("unlocked_book_entries", "已解锁图鉴条目"),
    _MetricSpec("peak_standard", "竞技赛季", season_limited=True),
    _MetricSpec("peak_standard_win_rate", "竞技胜率", season_limited=True),
    _MetricSpec("peak_standard_matches", "竞技场次", season_limited=True),
    _MetricSpec("peak_wild", "狂野赛季", season_limited=True),
    _MetricSpec("peak_wild_win_rate", "狂野胜率", season_limited=True),
    _MetricSpec("peak_wild_matches", "狂野场次", season_limited=True),
    _MetricSpec("peak_expert", "专家赛季", season_limited=True),
    _MetricSpec("peak_expert_win_rate", "专家胜率", season_limited=True),
    _MetricSpec("peak_expert_matches", "专家场次", season_limited=True),
    _MetricSpec("peak_total_matches", "巅峰总场次", season_limited=True),
)

_CACHE_LOCK = asyncio.Lock()
PERCENT_FINE_THRESHOLD = 10
_PEAK_RANK_NAMES = {
    0: "学徒",
    1: "猛将",
    2: "天骄",
    3: "王者",
    4: "圣皇",
    5: "宇宙圣皇",
}


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


def _metric_from_rank(result: RankLookupResult | None) -> int | None:
    if result is None:
        return None
    return result.score


def _positive_int(value: object) -> int | None:
    try:
        number = int(cast("Any", value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _metric(
    value: int | None,
    *,
    season_sub_key: int | None = None,
    display: str | None = None,
) -> MetricValue:
    return {
        "value": value,
        "season_sub_key": season_sub_key,
        "display": display,
    }


def _rate_metric(
    wins: int,
    total: int,
    *,
    season_sub_key: int | None,
) -> MetricValue:
    if total <= 0:
        return _metric(None, season_sub_key=season_sub_key)

    value = round(wins / total * 1_000_000)
    return _metric(
        value,
        season_sub_key=season_sub_key,
        display=f"{wins}/{total}={wins / total * 100:.3f}%",
    )


def _format_peak_rating_score(value: int) -> str:
    rank, star = divmod(value, 100000)
    name = _PEAK_RANK_NAMES.get(rank, f"段位{rank}")
    return f"{name}{star}星"


def _format_metric_display(
    metric_key: str,
    value: int,
    display: object | None = None,
) -> str:
    if display not in (None, ""):
        return str(display)
    if metric_key in {"peak_standard", "peak_wild"}:
        return _format_peak_rating_score(value)
    if metric_key == "peak_expert":
        return f"{value}分"
    return str(value)


def _collect_metrics(  # noqa: PLR0913
    *,
    more_info: Any,
    unity_part_one: UnityPartOneInfo,
    unity_peak: UnityPeakInfo,
    rank_summary: PlayerRankSummary,
    autocard_rank_summary: RankLookupResult | None,
    peak_sub_key: int | None,
    peak_standard_score: int | None,
    peak_wild_score: int | None,
    peak_expert_score: int | None,
) -> dict[str, MetricValue]:
    breakdown = rank_summary.breakdown

    values: dict[str, MetricValue] = {
        "book_score": _metric(_metric_from_rank(rank_summary.book)),
        "achievement_score": _metric(
            _positive_int(getattr(more_info, "total_achieve", 0))
        ),
        "achievement_count": _metric(_positive_int(unity_part_one.achievement_num)),
        "pet_total_count": _metric(
            _positive_int(getattr(more_info, "pet_all_num", 0))
        ),
        "pet_kind_count": _metric(_positive_int(unity_part_one.pet_kind_num)),
        "countermark_count": _metric(_metric_from_rank(breakdown.countermark)),
        "outfit_suit_count": _metric(_metric_from_rank(breakdown.outfit_suit)),
        "outfit_part_count": _metric(_metric_from_rank(breakdown.outfit_part)),
        "mount_count": _metric(_metric_from_rank(breakdown.mount)),
        "skin_count": _metric(_positive_int(unity_part_one.skin_num)),
        "autocard_score": _metric(_metric_from_rank(autocard_rank_summary)),
        "unlocked_book_entries": _metric(_positive_int(breakdown.unlocked_count)),
    }

    if peak_sub_key is not None:
        total_matches = (
            unity_peak.current_j_all
            + unity_peak.current_k_all
            + unity_peak.current_z_all
        )
        if unity_peak.current_j_all > 0:
            standard_score = _positive_int(peak_standard_score)
            values["peak_standard"] = _metric(
                standard_score,
                season_sub_key=peak_sub_key,
                display=(
                    _format_metric_display("peak_standard", standard_score)
                    if standard_score is not None
                    else None
                ),
            )
            values["peak_standard_win_rate"] = _rate_metric(
                unity_peak.current_j_win,
                unity_peak.current_j_all,
                season_sub_key=peak_sub_key,
            )
            values["peak_standard_matches"] = _metric(
                _positive_int(unity_peak.current_j_all),
                season_sub_key=peak_sub_key,
                display=f"{unity_peak.current_j_all}场",
            )
        if unity_peak.current_k_all > 0:
            wild_score = _positive_int(peak_wild_score)
            values["peak_wild"] = _metric(
                wild_score,
                season_sub_key=peak_sub_key,
                display=(
                    _format_metric_display("peak_wild", wild_score)
                    if wild_score is not None
                    else None
                ),
            )
            values["peak_wild_win_rate"] = _rate_metric(
                unity_peak.current_k_win,
                unity_peak.current_k_all,
                season_sub_key=peak_sub_key,
            )
            values["peak_wild_matches"] = _metric(
                _positive_int(unity_peak.current_k_all),
                season_sub_key=peak_sub_key,
                display=f"{unity_peak.current_k_all}场",
            )
        if unity_peak.current_z_all > 0:
            expert_score = _positive_int(peak_expert_score)
            values["peak_expert"] = _metric(
                expert_score,
                season_sub_key=peak_sub_key,
                display=(
                    _format_metric_display("peak_expert", expert_score)
                    if expert_score is not None
                    else None
                ),
            )
            values["peak_expert_win_rate"] = _rate_metric(
                unity_peak.current_z_win,
                unity_peak.current_z_all,
                season_sub_key=peak_sub_key,
            )
            values["peak_expert_matches"] = _metric(
                _positive_int(unity_peak.current_z_all),
                season_sub_key=peak_sub_key,
                display=f"{unity_peak.current_z_all}场",
            )
        if total_matches > 0:
            values["peak_total_matches"] = _metric(
                _positive_int(total_matches),
                season_sub_key=peak_sub_key,
                display=f"{total_matches}场",
            )

    return {
        key: value
        for key, value in values.items()
        if value.get("value") is not None
    }


def _max_cached_players() -> int:
    return max(1, get_local_rank_config().max_players)


def _sqlite_cache_path() -> Path:
    return get_local_rank_config().path


def _connect_cache() -> sqlite3.Connection:
    path = _sqlite_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _ensure_cache_schema(conn)
    return conn


def _ensure_cache_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            nick TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    player_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(players)").fetchall()
    }
    if "sample_enabled" not in player_columns:
        conn.execute(
            "ALTER TABLE players ADD COLUMN sample_enabled INTEGER NOT NULL DEFAULT 1"
        )
    if "sampled_at" not in player_columns:
        conn.execute("ALTER TABLE players ADD COLUMN sampled_at TEXT")
        conn.execute(
            """
            UPDATE players
            SET sampled_at = updated_at
            WHERE sample_enabled = 1
              AND sampled_at IS NULL
            """
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metrics (
            user_id INTEGER NOT NULL,
            metric_key TEXT NOT NULL,
            value INTEGER NOT NULL,
            season_sub_key INTEGER,
            display TEXT,
            PRIMARY KEY (user_id, metric_key),
            FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_players_sample
        ON players(sample_enabled, user_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_metrics_rank
        ON metrics(metric_key, season_sub_key, value DESC, user_id)
        """
    )
    conn.commit()


def _write_player_metrics(  # noqa: PLR0913
    conn: sqlite3.Connection,
    *,
    player_id: int,
    nick: str,
    metrics: dict[str, MetricValue],
    updated_at: str | None = None,
    sample_enabled: bool = True,
) -> None:
    timestamp = updated_at or datetime.now(timezone.utc).isoformat()
    sample_flag = 1 if sample_enabled else 0
    sampled_at = timestamp if sample_enabled else None
    conn.execute(
        """
        INSERT INTO players(user_id, nick, updated_at, sample_enabled, sampled_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            nick = excluded.nick,
            updated_at = CASE
                WHEN excluded.sample_enabled = 1 THEN excluded.updated_at
                ELSE players.updated_at
            END,
            sample_enabled = CASE
                WHEN excluded.sample_enabled = 1 THEN 1
                ELSE players.sample_enabled
            END,
            sampled_at = CASE
                WHEN excluded.sample_enabled = 1 THEN excluded.sampled_at
                ELSE players.sampled_at
            END
        """,
        (player_id, nick, timestamp, sample_flag, sampled_at),
    )
    for key, metric in metrics.items():
        value = _positive_int(metric.get("value"))
        if value is None:
            continue

        season_sub_key = metric.get("season_sub_key")
        display = metric.get("display")
        conn.execute(
            """
            INSERT INTO metrics(user_id, metric_key, value, season_sub_key, display)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, metric_key) DO UPDATE SET
                value = excluded.value,
                season_sub_key = excluded.season_sub_key,
                display = excluded.display
            """,
            (
                player_id,
                key,
                value,
                season_sub_key if isinstance(season_sub_key, int) else None,
                None if display in (None, "") else str(display),
            ),
        )


def _format_percent(value: float) -> str:
    precision = 2 if value < PERCENT_FINE_THRESHOLD else 1
    return f"{value:.{precision}f}".rstrip("0").rstrip(".")


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
                conn.commit()
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
            conn.commit()
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
