# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from ironsbot.services.seer import local_rank_formatting

if TYPE_CHECKING:
    from ironsbot.services.seer.rank import PlayerRankSummary, RankLookupResult
    from ironsbot.services.seer.sequ_extra import UnityPartOneInfo, UnityPeakInfo

MetricValue = dict[str, int | str | None]


@dataclass(frozen=True, slots=True)
class MetricSpec:
    key: str
    title: str
    season_limited: bool = False


LOCAL_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("book_score", "图鉴积分"),
    MetricSpec("achievement_score", "成就点数"),
    MetricSpec("achievement_count", "成就数量"),
    MetricSpec("pet_total_count", "精灵数量"),
    MetricSpec("pet_kind_count", "精灵图鉴"),
    MetricSpec("countermark_count", "刻印图鉴"),
    MetricSpec("outfit_suit_count", "套装图鉴"),
    MetricSpec("outfit_part_count", "部件图鉴"),
    MetricSpec("mount_count", "座驾图鉴"),
    MetricSpec("skin_count", "皮肤图鉴"),
    MetricSpec("autocard_score", "群星牌积分"),
    MetricSpec("unlocked_book_entries", "已解锁图鉴条目"),
    MetricSpec("peak_standard", "竞技赛季", season_limited=True),
    MetricSpec("peak_standard_win_rate", "竞技胜率", season_limited=True),
    MetricSpec("peak_standard_matches", "竞技场次", season_limited=True),
    MetricSpec("peak_wild", "狂野赛季", season_limited=True),
    MetricSpec("peak_wild_win_rate", "狂野胜率", season_limited=True),
    MetricSpec("peak_wild_matches", "狂野场次", season_limited=True),
    MetricSpec("peak_expert", "专家赛季", season_limited=True),
    MetricSpec("peak_expert_win_rate", "专家胜率", season_limited=True),
    MetricSpec("peak_expert_matches", "专家场次", season_limited=True),
    MetricSpec("peak_total_matches", "巅峰总场次", season_limited=True),
)


def metric_from_rank(result: RankLookupResult | None) -> int | None:
    if result is None:
        return None
    return result.score


def positive_int(value: object) -> int | None:
    try:
        number = int(cast("Any", value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def metric(
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


def rate_metric(
    wins: int,
    total: int,
    *,
    season_sub_key: int | None,
) -> MetricValue:
    if total <= 0:
        return metric(None, season_sub_key=season_sub_key)

    value = round(wins / total * 1_000_000)
    return metric(
        value,
        season_sub_key=season_sub_key,
        display=f"{wins}/{total}={wins / total * 100:.3f}%",
    )


def collect_metrics(  # noqa: PLR0913
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
        "book_score": metric(metric_from_rank(rank_summary.book)),
        "achievement_score": metric(
            positive_int(getattr(more_info, "total_achieve", 0))
        ),
        "achievement_count": metric(positive_int(unity_part_one.achievement_num)),
        "pet_total_count": metric(
            positive_int(getattr(more_info, "pet_all_num", 0))
        ),
        "pet_kind_count": metric(positive_int(unity_part_one.pet_kind_num)),
        "countermark_count": metric(metric_from_rank(breakdown.countermark)),
        "outfit_suit_count": metric(metric_from_rank(breakdown.outfit_suit)),
        "outfit_part_count": metric(metric_from_rank(breakdown.outfit_part)),
        "mount_count": metric(metric_from_rank(breakdown.mount)),
        "skin_count": metric(positive_int(unity_part_one.skin_num)),
        "autocard_score": metric(metric_from_rank(autocard_rank_summary)),
        "unlocked_book_entries": metric(positive_int(breakdown.unlocked_count)),
    }

    if peak_sub_key is not None:
        total_matches = (
            unity_peak.current_j_all
            + unity_peak.current_k_all
            + unity_peak.current_z_all
        )
        if unity_peak.current_j_all > 0:
            standard_score = positive_int(peak_standard_score)
            values["peak_standard"] = metric(
                standard_score,
                season_sub_key=peak_sub_key,
                display=(
                    local_rank_formatting.format_metric_display(
                        "peak_standard",
                        standard_score,
                    )
                    if standard_score is not None
                    else None
                ),
            )
            values["peak_standard_win_rate"] = rate_metric(
                unity_peak.current_j_win,
                unity_peak.current_j_all,
                season_sub_key=peak_sub_key,
            )
            values["peak_standard_matches"] = metric(
                positive_int(unity_peak.current_j_all),
                season_sub_key=peak_sub_key,
                display=f"{unity_peak.current_j_all}场",
            )
        if unity_peak.current_k_all > 0:
            wild_score = positive_int(peak_wild_score)
            values["peak_wild"] = metric(
                wild_score,
                season_sub_key=peak_sub_key,
                display=(
                    local_rank_formatting.format_metric_display(
                        "peak_wild",
                        wild_score,
                    )
                    if wild_score is not None
                    else None
                ),
            )
            values["peak_wild_win_rate"] = rate_metric(
                unity_peak.current_k_win,
                unity_peak.current_k_all,
                season_sub_key=peak_sub_key,
            )
            values["peak_wild_matches"] = metric(
                positive_int(unity_peak.current_k_all),
                season_sub_key=peak_sub_key,
                display=f"{unity_peak.current_k_all}场",
            )
        if unity_peak.current_z_all > 0:
            expert_score = positive_int(peak_expert_score)
            values["peak_expert"] = metric(
                expert_score,
                season_sub_key=peak_sub_key,
                display=(
                    local_rank_formatting.format_metric_display(
                        "peak_expert",
                        expert_score,
                    )
                    if expert_score is not None
                    else None
                ),
            )
            values["peak_expert_win_rate"] = rate_metric(
                unity_peak.current_z_win,
                unity_peak.current_z_all,
                season_sub_key=peak_sub_key,
            )
            values["peak_expert_matches"] = metric(
                positive_int(unity_peak.current_z_all),
                season_sub_key=peak_sub_key,
                display=f"{unity_peak.current_z_all}场",
            )
        if total_matches > 0:
            values["peak_total_matches"] = metric(
                positive_int(total_matches),
                season_sub_key=peak_sub_key,
                display=f"{total_matches}场",
            )

    return {
        key: value
        for key, value in values.items()
        if value.get("value") is not None
    }
