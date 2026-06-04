# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nonebot.log import logger

from ..config import plugin_config
from ._rank import PlayerRankSummary, RankLookupResult, is_pet_kind_rank_anomaly_user
from ._sequ_extra import UnityPartOneInfo, UnityPeakInfo

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
    _MetricSpec("unlocked_book_entries", "已解锁图鉴条目"),
    _MetricSpec("peak_standard", "竞技赛季", season_limited=True),
    _MetricSpec("peak_standard_win_rate", "竞技胜率", season_limited=True),
    _MetricSpec("peak_wild", "狂野赛季", season_limited=True),
    _MetricSpec("peak_wild_win_rate", "狂野胜率", season_limited=True),
    _MetricSpec("peak_expert", "专家赛季", season_limited=True),
    _MetricSpec("peak_expert_win_rate", "专家胜率", season_limited=True),
)

_CACHE_LOCK = asyncio.Lock()
PERCENT_FINE_THRESHOLD = 10


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
    metric_counts: dict[str, int]


def _metric_from_rank(result: RankLookupResult | None) -> int | None:
    if result is None:
        return None
    return result.score


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)
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


def _collect_metrics(  # noqa: PLR0913
    *,
    more_info: Any,
    unity_part_one: UnityPartOneInfo,
    unity_peak: UnityPeakInfo,
    rank_summary: PlayerRankSummary,
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
        "unlocked_book_entries": _metric(_positive_int(breakdown.unlocked_count)),
    }

    if peak_sub_key is not None:
        if unity_peak.current_j_all > 0:
            values["peak_standard"] = _metric(
                _positive_int(peak_standard_score),
                season_sub_key=peak_sub_key,
            )
            values["peak_standard_win_rate"] = _rate_metric(
                unity_peak.current_j_win,
                unity_peak.current_j_all,
                season_sub_key=peak_sub_key,
            )
        if unity_peak.current_k_all > 0:
            values["peak_wild"] = _metric(
                _positive_int(peak_wild_score),
                season_sub_key=peak_sub_key,
            )
            values["peak_wild_win_rate"] = _rate_metric(
                unity_peak.current_k_win,
                unity_peak.current_k_all,
                season_sub_key=peak_sub_key,
            )
        if unity_peak.current_z_all > 0:
            values["peak_expert"] = _metric(
                _positive_int(peak_expert_score),
                season_sub_key=peak_sub_key,
            )
            values["peak_expert_win_rate"] = _rate_metric(
                unity_peak.current_z_win,
                unity_peak.current_z_all,
                season_sub_key=peak_sub_key,
            )

    return {
        key: value
        for key, value in values.items()
        if value.get("value") is not None
    }


def _empty_cache() -> dict[str, Any]:
    return {"version": 1, "players": {}}


def _read_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_cache()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"failed to read custom Seer local rank cache: {e}")
        return _empty_cache()

    if not isinstance(data, dict):
        return _empty_cache()

    players = data.get("players")
    if not isinstance(players, dict):
        data["players"] = {}

    data["version"] = 1
    return data


def _write_cache(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _format_percent(value: float) -> str:
    precision = 2 if value < PERCENT_FINE_THRESHOLD else 1
    return f"{value:.{precision}f}".rstrip("0").rstrip(".")


def _format_local_rank(  # noqa: PLR0913
    *,
    players: dict[str, Any],
    metric_key: str,
    title: str,
    current_value: int | None,
    display_value: object | None = None,
    season_sub_key: int | None = None,
) -> tuple[str, str] | None:
    if current_value is None:
        return None

    values: list[int] = []
    for record in players.values():
        if not isinstance(record, dict):
            continue

        metrics = record.get("metrics")
        if not isinstance(metrics, dict):
            continue

        metric = metrics.get(metric_key)
        if not isinstance(metric, dict):
            continue

        if (
            season_sub_key is not None
            and metric.get("season_sub_key") != season_sub_key
        ):
            continue

        value = _positive_int(metric.get("value"))
        if value is not None:
            values.append(value)

    if not values:
        return None

    rank = 1 + sum(value > current_value for value in values)
    tie_count = sum(value == current_value for value in values)
    sample_count = len(values)
    percent_text = _format_percent(rank / sample_count * 100)
    sample_rank_text = f"样本前{percent_text}%"
    tie_text = f"，并列 {tie_count} 人" if tie_count > 1 else ""
    display_text = current_value if display_value in (None, "") else display_value

    summary_text = (
        f"{title}：样本前{percent_text}%"
        f"（{display_text}，样本 {sample_count} 人{tie_text}）"
    )
    return summary_text, sample_rank_text


def _format_summary(
    *,
    players: dict[str, Any],
    current_metrics: dict[str, MetricValue],
    peak_sub_key: int | None,
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
            players=players,
            metric_key=spec.key,
            title=spec.title,
            current_value=value,
            display_value=metric.get("display"),
            season_sub_key=season_sub_key,
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


def get_local_rank_entries(  # noqa: C901
    metric_key: str,
    *,
    limit: int = 20,
    season_sub_key: int | None = None,
) -> tuple[list[LocalRankEntry], int]:
    cache = _read_cache(plugin_config.seer_query_local_rank_path)
    players = cache.get("players")
    if not isinstance(players, dict):
        return [], 0

    rows: list[tuple[int, int, str, str]] = []
    for record in players.values():
        if not isinstance(record, dict):
            continue

        metrics = record.get("metrics")
        if not isinstance(metrics, dict):
            continue

        metric = metrics.get(metric_key)
        if not isinstance(metric, dict):
            continue

        if (
            season_sub_key is not None
            and metric.get("season_sub_key") != season_sub_key
        ):
            continue

        value = _positive_int(metric.get("value"))
        if value is None:
            continue

        try:
            user_id = int(record.get("user_id", 0))
        except (TypeError, ValueError):
            user_id = 0
        if user_id <= 0:
            continue

        nick = str(record.get("nick") or "未知")
        display = str(metric.get("display") or value)
        rows.append((value, user_id, nick, display))

    rows.sort(key=lambda item: (-item[0], item[1]))

    entries: list[LocalRankEntry] = []
    last_value: int | None = None
    current_rank = 0
    for index, (value, user_id, nick, display) in enumerate(rows, 1):
        if value != last_value:
            current_rank = index
            last_value = value

        if len(entries) >= limit:
            break

        entries.append(
            LocalRankEntry(
                rank=current_rank,
                user_id=user_id,
                nick=nick,
                value=value,
                display=display,
            )
        )

    return entries, len(rows)


def get_cached_player_ids() -> list[int]:
    cache = _read_cache(plugin_config.seer_query_local_rank_path)
    players = cache.get("players")
    if not isinstance(players, dict):
        return []

    player_ids: list[int] = []
    for player_id in players:
        try:
            value = int(player_id)
        except (TypeError, ValueError):
            continue
        if value > 0:
            player_ids.append(value)

    return sorted(player_ids)


def get_local_rank_cache_stats() -> LocalRankCacheStats:
    cache = _read_cache(plugin_config.seer_query_local_rank_path)
    players = cache.get("players")
    if not isinstance(players, dict):
        return LocalRankCacheStats(player_count=0, metric_counts={})

    metric_counts = {spec.title: 0 for spec in _LOCAL_METRICS}
    for record in players.values():
        if not isinstance(record, dict):
            continue

        metrics = record.get("metrics")
        if not isinstance(metrics, dict):
            continue

        for spec in _LOCAL_METRICS:
            metric = metrics.get(spec.key)
            if not isinstance(metric, dict):
                continue
            if _positive_int(metric.get("value")) is not None:
                metric_counts[spec.title] += 1

    return LocalRankCacheStats(
        player_count=len(players),
        metric_counts=metric_counts,
    )


async def upsert_local_rank_metrics(
    *,
    player_id: int,
    nick: str,
    current_metrics: dict[str, MetricValue],
    peak_sub_key: int | None,
) -> LocalRankSummary:
    if is_pet_kind_rank_anomaly_user(player_id):
        path = plugin_config.seer_query_local_rank_path
        async with _CACHE_LOCK:
            cache = _read_cache(path)
            players = cache.setdefault("players", {})
            if players.pop(str(player_id), None) is not None:
                _write_cache(path, cache)
        return LocalRankSummary()

    path = plugin_config.seer_query_local_rank_path
    async with _CACHE_LOCK:
        cache = _read_cache(path)
        players = cache.setdefault("players", {})
        old_record = players.get(str(player_id))
        old_metrics = {}
        if isinstance(old_record, dict) and isinstance(old_record.get("metrics"), dict):
            old_metrics = dict(old_record["metrics"])

        players[str(player_id)] = {
            "user_id": player_id,
            "nick": nick,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "metrics": {**old_metrics, **current_metrics},
        }
        _write_cache(path, cache)
        return _format_summary(
            players=players,
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
