from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from ironsbot.services.seer.sequ_extra import fetch_unity_peak, fetch_unity_peak_partial

_WILD_FIRST_PARAM = 124791
_STANDARD_FIRST_PARAM = 124801
_EXPECTED_STAR = 3
_EXPECTED_RANK = 2
_EXPECTED_MATCHES = 20
_EXPECTED_WILD_STAR = 5
_EXPECTED_WILD_RANK = 6
_EXPECTED_WILD_HISTORY_STAR = 7
_EXPECTED_WILD_HISTORY_RANK = 8
_EXPECTED_WILD_WINS = 9
_EXPECTED_WILD_MATCHES = 11
_EXPECTED_EXPERT_SCORE = 1200
_EXPECTED_EXPERT_HISTORY_SCORE = 1500
_EXPECTED_EXPERT_WINS = 8
_EXPECTED_EXPERT_MATCHES = 10


class _PeakGame:
    def __init__(self, timeout_param: int = _WILD_FIRST_PARAM) -> None:
        self.params: list[int] = []
        self._timeout_param = timeout_param

    async def send_and_wait(
        self,
        _command_id: int,
        _player_id: int,
        param: int,
    ) -> tuple[SimpleNamespace, SimpleNamespace]:
        self.params.append(param)
        if param == self._timeout_param:
            await asyncio.Event().wait()
        values = {
            124801: (3 << 16) + 2,
            124802: (4 << 16) + 1,
            124804: 12,
            124805: 20,
            124791: (5 << 16) + 6,
            124792: (7 << 16) + 8,
            124793: 9,
            124794: 11,
            129441: 1200,
            129443: 1500,
            129446: 8,
            129447: 10,
        }
        return SimpleNamespace(user_id=654321), SimpleNamespace(value=values[param])


@pytest.mark.asyncio
async def test_peak_logs_raw_values_worker_and_decoded_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        result = await fetch_unity_peak_partial(
            _PeakGame(timeout_param=-1),
            712_345_678,
            timeout_seconds=0.2,
        )
    assert result.query_id != "-"
    assert result.available_modes == frozenset(("standard", "wild", "expert"))
    assert f"peak base start query={result.query_id}" in caplog.text
    response = next(
        record.getMessage()
        for record in caplog.records
        if "peak field response" in record.getMessage()
        and "param=124791" in record.getMessage()
    )
    assert f"query={result.query_id}" in response
    assert "worker=654321" in response
    assert "value=327686 hex=00050006" in response
    assert "current_k_star=5, current_k_rank=6" in caplog.text
    assert f"peak base complete query={result.query_id}" in caplog.text


@pytest.mark.asyncio
async def test_mode_failure_logs_previously_received_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        result = await fetch_unity_peak_partial(
            _PeakGame(timeout_param=124794),
            712_345_678,
            timeout_seconds=0.1,
        )
    assert result.error_for("wild") == "查询超时"
    assert "param=124791" in caplog.text and "value=327686" in caplog.text
    assert (
        "completed_params=(124791, 124792, 124793) error_type=TimeoutError"
        in caplog.text
    )
    assert result.info.current_k_star == 0


@pytest.mark.asyncio
async def test_full_peak_query_uses_same_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        result = await fetch_unity_peak(_PeakGame(timeout_param=-1), 712_345_678)
    assert result.current_k_star == _EXPECTED_WILD_STAR
    assert "param=124791" in caplog.text
    assert "peak base complete query=" in caplog.text


@pytest.mark.asyncio
async def test_peak_partial_continues_to_later_modes_after_one_mode_times_out(
) -> None:
    result = await fetch_unity_peak_partial(
        _PeakGame(),
        712_345_678,
        timeout_seconds=0.1,
    )

    assert result.available_modes == frozenset(("standard", "expert"))
    assert result.info.current_j_star == _EXPECTED_STAR
    assert result.info.current_j_rank == _EXPECTED_RANK
    assert result.info.current_j_all == _EXPECTED_MATCHES
    assert result.error_for("wild") == "查询超时"
    assert result.error_for("expert") is None
    assert result.info.current_k_star == 0
    assert result.info.current_k_rank == 0
    assert result.info.history_k_star == 0
    assert result.info.history_k_rank == 0
    assert result.info.current_z_score == _EXPECTED_EXPERT_SCORE
    assert result.info.history_z_score == _EXPECTED_EXPERT_HISTORY_SCORE
    assert result.info.current_z_win == _EXPECTED_EXPERT_WINS
    assert result.info.current_z_all == _EXPECTED_EXPERT_MATCHES


@pytest.mark.asyncio
async def test_peak_partial_keeps_later_modes_aligned_after_standard_timeout(
) -> None:
    result = await fetch_unity_peak_partial(
        _PeakGame(timeout_param=_STANDARD_FIRST_PARAM),
        712_345_678,
        timeout_seconds=0.1,
    )

    assert result.available_modes == frozenset(("wild", "expert"))
    assert result.info.current_j_star == 0
    assert result.info.current_j_rank == 0
    assert result.info.history_j_star == 0
    assert result.info.history_j_rank == 0
    assert result.error_for("standard") == "查询超时"
    assert result.info.current_k_star == _EXPECTED_WILD_STAR
    assert result.info.current_k_rank == _EXPECTED_WILD_RANK
    assert result.info.history_k_star == _EXPECTED_WILD_HISTORY_STAR
    assert result.info.history_k_rank == _EXPECTED_WILD_HISTORY_RANK
    assert result.info.current_k_win == _EXPECTED_WILD_WINS
    assert result.info.current_k_all == _EXPECTED_WILD_MATCHES
    assert result.info.current_z_score == _EXPECTED_EXPERT_SCORE
    assert result.info.history_z_score == _EXPECTED_EXPERT_HISTORY_SCORE
    assert result.info.current_z_win == _EXPECTED_EXPERT_WINS
    assert result.info.current_z_all == _EXPECTED_EXPERT_MATCHES
