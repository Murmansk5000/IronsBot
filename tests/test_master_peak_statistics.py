from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from ironsbot.services.seer.local_rank_metrics import collect_metrics, rate_metric
from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.peak_modes import PEAK_MODE_NAMES
from ironsbot.services.seer.player_peak_formatting import format_compact_peak_section
from ironsbot.services.seer.rank_models import PeakSeasonRankSummary, PlayerRankSummary
from ironsbot.services.seer.sequ_extra import UnityPartOneInfo, UnityPeakInfo

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank_metrics import MetricValue

SEASON = 20260904
MASTER_SCORE = 400004
MATCHES = 3
WINS = 1
MODE_FIELDS = (
    ("standard", "j", "竞技"),
    ("wild", "k", "狂野"),
    ("expert", "z", "专家"),
    ("master", "m", "大师"),
)


def _peak() -> UnityPeakInfo:
    return UnityPeakInfo(
        current_j_rank=4,
        current_j_star=4,
        current_j_win=WINS,
        current_j_all=MATCHES,
        current_k_rank=4,
        current_k_star=4,
        current_k_win=WINS,
        current_k_all=MATCHES,
        current_z_score=1500,
        current_z_win=WINS,
        current_z_all=MATCHES,
        current_m_rank=4,
        current_m_star=4,
        history_m_rank=4,
        history_m_star=5,
        current_m_win=WINS,
        current_m_all=MATCHES,
    )


def _metrics(
    peak: UnityPeakInfo,
    modes: frozenset[str] | None = None,
) -> dict[str, MetricValue]:
    return collect_metrics(
        more_info=SimpleNamespace(),
        unity_part_one=UnityPartOneInfo(),
        unity_peak=peak,
        rank_summary=PlayerRankSummary.empty(),
        autocard_rank_summary=None,
        peak_sub_key=SEASON,
        master_sub_key=SEASON,
        peak_standard_score=MASTER_SCORE,
        peak_wild_score=MASTER_SCORE,
        peak_expert_score=1500,
        peak_master_score=MASTER_SCORE,
        available_modes=modes,
    )


def _message(
    peak: UnityPeakInfo,
    modes: frozenset[str] | None = None,
    errors: dict[str, str] | None = None,
) -> str:
    return format_compact_peak_section(
        peak,
        PeakSeasonRankSummary.empty(),
        LocalRankSummary(),
        fetched_at=None,
        available_modes=modes,
        mode_errors=errors,
    )


def test_four_mode_rates_share_personal_counts_and_precision() -> None:
    peak = _peak()
    message = _message(peak)
    metrics = _metrics(peak)
    for mode, _prefix, title in MODE_FIELDS:
        line = next(line for line in message.splitlines() if line.startswith(title))
        assert "场次3｜胜率1/3=33.333%" in line
        assert metrics[f"peak_{mode}_win_rate"]["display"] == "1/3=33.333%"
        assert metrics[f"peak_{mode}_matches"]["value"] == MATCHES
        assert metrics[f"peak_{mode}_matches"]["season_sub_key"] == SEASON
    assert "大师：圣皇4星｜历史圣皇5星" in message
    assert "巅峰总场次：12场" in message
    assert metrics["peak_total_matches"]["value"] == MATCHES * len(MODE_FIELDS)


@pytest.mark.parametrize(("mode", "prefix", "title"), MODE_FIELDS)
def test_successful_zero_matches_do_not_compute_a_rate(
    mode: str, prefix: str, title: str
) -> None:
    peak = replace(_peak(), **{f"current_{prefix}_win": 0, f"current_{prefix}_all": 0})
    line = next(line for line in _message(peak).splitlines() if line.startswith(title))
    assert "胜率" not in line
    assert "数据异常" not in line
    assert f"peak_{mode}_win_rate" not in _metrics(peak)
    assert "peak_total_matches" in _metrics(peak)


@pytest.mark.parametrize(("mode", "prefix", "title"), MODE_FIELDS)
@pytest.mark.parametrize(("wins", "total"), ((2, 1), (-1, 3), (0, -1), (1, 0)))
def test_invalid_counts_are_visible_and_never_enter_samples(
    mode: str, prefix: str, title: str, wins: int, total: int
) -> None:
    peak = replace(
        _peak(), **{f"current_{prefix}_win": wins, f"current_{prefix}_all": total}
    )
    message = _message(peak)
    line = next(line for line in message.splitlines() if line.startswith(title))
    assert "场次数据异常" in line
    assert "胜率" not in line
    assert "巅峰总场次" not in message
    metrics = _metrics(peak)
    assert not any(key.startswith(f"peak_{mode}") for key in metrics)
    assert "peak_total_matches" not in metrics
    for other in PEAK_MODE_NAMES - {mode}:
        assert f"peak_{other}_win_rate" in metrics


@pytest.mark.parametrize(("mode", "_prefix", "title"), MODE_FIELDS)
def test_missing_mode_uses_error_and_cannot_publish_stale_samples(
    mode: str, _prefix: str, title: str
) -> None:
    modes = PEAK_MODE_NAMES - {mode}
    message = _message(_peak(), modes, {mode: "查询超时"})
    line = next(line for line in message.splitlines() if line.startswith(title))
    assert "暂未获取（查询超时）" in line
    assert "场次" not in line
    assert "胜率" not in line
    assert "巅峰总场次" not in message
    metrics = _metrics(_peak(), modes)
    assert not any(key.startswith(f"peak_{mode}") for key in metrics)
    assert "peak_total_matches" not in metrics


def test_empty_available_modes_is_not_the_default_all_modes() -> None:
    metrics = _metrics(_peak(), frozenset())
    assert not any(key.startswith("peak_") for key in metrics)
    assert "巅峰总场次" not in _message(_peak(), frozenset())


@pytest.mark.parametrize("failure", ("查询超时", "连接已断开", None))
def test_master_personal_statistics_do_not_come_from_rank_lookup(
    failure: str | None,
) -> None:
    ranks = PeakSeasonRankSummary.empty()
    ranks.master.score = 300001
    ranks.master.rank = 12
    ranks.master.failure = failure
    ranks.master.queried = True
    message = format_compact_peak_section(
        _peak(), ranks, LocalRankSummary(), fetched_at=None
    )
    line = next(line for line in message.splitlines() if line.startswith("大师"))
    assert "大师：圣皇4星｜历史圣皇5星｜场次3｜胜率1/3=33.333%" in line
    assert "王者1星" not in line


@pytest.mark.parametrize(("wins", "total"), ((0, 0), (2, 1), (-1, 3), (0, -1)))
def test_rate_metric_rejects_invalid_or_empty_counts(wins: int, total: int) -> None:
    result = rate_metric(wins, total, season_sub_key=SEASON)
    assert result["value"] is None
    assert result["display"] is None
    assert result["season_sub_key"] == SEASON


def test_boolean_counts_cannot_publish_numeric_samples() -> None:
    peak = replace(_peak(), current_m_win=True)
    assert "场次数据异常" in _message(peak)
    assert "peak_master" not in _metrics(peak)
    assert "peak_total_matches" not in _metrics(peak)
