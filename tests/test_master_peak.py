from __future__ import annotations

import struct
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ironsbot.services.seer.local_rank_metrics import collect_metrics
from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.peak import PeakPeriodTimes, peak_pet_period
from ironsbot.services.seer.peak_modes import (
    PEAK_MODE_NAMES,
    PEAK_MODES,
    PeakType,
    combined_peak_season,
)
from ironsbot.services.seer.player_peak_formatting import format_compact_peak_section
from ironsbot.services.seer.player_query import (
    calculate_player_peak_scores,
    validate_player_peak_season,
)
from ironsbot.services.seer.rank_models import (
    PeakSeasonRankSummary,
    PlayerRankSummary,
    RankLookupResult,
)
from ironsbot.services.seer.sequ_extra import (
    UnityPartOneInfo,
    UnityPeakInfo,
    fetch_unity_peak,
    parse_unity_peak,
)

REGULAR = 20260828
MASTER = 20260904
SCORE = 400004
WINS = 31


def test_verified_master_parameters_and_packet_slots() -> None:
    mode = PEAK_MODES[PeakType.MASTER]
    assert mode.personal_params == (408302, 408304, 408315)
    assert mode.pet_keys == (259, 258, 257)
    assert mode.suit_keys == (260, 261)
    assert mode.title_keys == (262, 263)
    info = parse_unity_peak(struct.pack("!15I", *([0] * 12), 262148, 327684, WINS))
    assert (info.current_m_rank, info.current_m_star) == (4, 4)
    assert (info.history_m_rank, info.history_m_star) == (4, 5)
    assert info.current_m_win == WINS
    assert info.current_m_all is None
    assert calculate_player_peak_scores(info).master == SCORE


@pytest.mark.asyncio
async def test_master_lookup_reads_no_unrelated_personal_fields() -> None:
    params: list[int] = []

    async def packet(_command: int, _player: int, param: int) -> tuple[None, object]:
        params.append(param)
        return None, SimpleNamespace(
            value={408302: 262148, 408304: 262148, 408315: WINS}[param]
        )

    info = await fetch_unity_peak(
        SimpleNamespace(send_and_wait=packet), 700001001, mode="master"
    )
    assert tuple(params) == PEAK_MODES[PeakType.MASTER].personal_params
    assert info.current_m_win == WINS
    assert info.current_m_all is None


def _metrics(count: int | None, modes: frozenset[str] = PEAK_MODE_NAMES) -> dict:
    return collect_metrics(
        more_info=SimpleNamespace(),
        unity_part_one=UnityPartOneInfo(),
        unity_peak=UnityPeakInfo(
            current_j_all=10,
            current_k_all=20,
            current_z_all=30,
            current_m_all=count,
            current_m_win=WINS,
        ),
        rank_summary=PlayerRankSummary.empty(),
        autocard_rank_summary=None,
        peak_sub_key=REGULAR,
        master_sub_key=MASTER,
        peak_standard_score=None,
        peak_wild_score=None,
        peak_expert_score=None,
        peak_master_score=SCORE,
        available_modes=modes,
    )


def test_unknown_master_count_is_not_zero_or_a_three_mode_total() -> None:
    metrics = _metrics(None)
    assert metrics["peak_master"]["season_sub_key"] == MASTER
    assert "peak_master_matches" not in metrics
    assert "peak_master_win_rate" not in metrics
    assert "peak_total_matches" not in metrics


def test_total_requires_all_modes_and_both_seasons() -> None:
    count = 40
    metric = _metrics(count)["peak_total_matches"]
    assert metric["value"] == 100  # noqa: PLR2004
    assert metric["season_sub_key"] == combined_peak_season(REGULAR, MASTER)
    assert "peak_total_matches" not in _metrics(count, frozenset(("master",)))
    assert combined_peak_season(None, MASTER) is None
    scope = combined_peak_season(REGULAR, MASTER)
    assert scope != combined_peak_season(REGULAR + 1, MASTER)
    assert scope != combined_peak_season(REGULAR, MASTER + 1)
    assert scope != REGULAR


@pytest.mark.parametrize("failure", ["查询超时", "连接已断开", None])
def test_old_master_rank_never_replaces_personal_score(failure: str | None) -> None:
    info = UnityPeakInfo(current_m_rank=4, current_m_star=4, current_m_win=WINS)
    rank = RankLookupResult(
        title="大师",
        score_name="",
        rank=10,
        score=300001,
        failure=failure,
        fallback_cached_at=1800000000,
    )
    summary = PeakSeasonRankSummary.from_results({"master_peak": rank})
    validated = validate_player_peak_season(
        info, calculate_player_peak_scores(info), summary
    )
    assert validated.scores.master == SCORE
    assert validated.unity_peak.current_m_win == WINS
    message = format_compact_peak_section(
        info, summary, LocalRankSummary(), fetched_at=None
    )
    assert "大师：圣皇4星" in message
    assert "场次及胜率暂无法确认" in message
    assert "巅峰总场次" not in message


def test_master_month_and_season_keys_do_not_use_regular_season() -> None:
    times = PeakPeriodTimes(
        datetime(2026, 9, 4, tzinfo=timezone.utc),
        datetime(2026, 11, 27, tzinfo=timezone.utc),
    )
    season = peak_pet_period(times, monthly=False)
    month = peak_pet_period(times, monthly=True)
    assert season is not None and month is not None
    assert season.sub_key == MASTER
    assert month.sub_key == MASTER + 1_000_000_000


@pytest.mark.asyncio
async def test_invalid_mode_cannot_read_packets() -> None:
    send = AsyncMock()
    with pytest.raises(ValueError):
        await fetch_unity_peak(
            SimpleNamespace(send_and_wait=send), 700001001, mode="unknown"
        )
    send.assert_not_awaited()
