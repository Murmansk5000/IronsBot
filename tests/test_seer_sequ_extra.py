from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from ironsbot.services.seer.sequ_extra import fetch_unity_peak_partial

if TYPE_CHECKING:
    from collections.abc import Coroutine


@pytest.fixture(autouse=True)
def no_protocol_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ironsbot.services.seer.sequ_extra.PEAK_QUERY_DELAY_SECONDS", 0)


@pytest.mark.asyncio
async def test_peak_modes_share_one_stage_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    limits: list[float] = []
    monkeypatch.setattr("ironsbot.core.tasks.monotonic", lambda: now[0])

    async def time_out(operation: Coroutine[Any, Any, Any], *, timeout: float) -> None:
        operation.close()
        limits.append(timeout)
        now[0] += timeout
        raise TimeoutError

    monkeypatch.setattr("ironsbot.services.seer.sequ_extra.asyncio.wait_for", time_out)
    result = await fetch_unity_peak_partial(
        _PeakGame(), 712_345_678, timeout_seconds=0.3
    )
    assert limits == pytest.approx([0.1, 0.1, 0.1])
    assert sum(limits) == pytest.approx(0.3)
    assert result.available_modes == frozenset()
    assert result.fetched_at is None
    assert all(
        result.error_for(mode) == "查询超时" for mode in ("standard", "wild", "expert")
    )


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
    ) -> tuple[None, SimpleNamespace]:
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
        return None, SimpleNamespace(value=values[param])


@pytest.mark.asyncio
async def test_peak_partial_continues_to_later_modes_after_one_mode_times_out() -> None:
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
async def test_peak_observation_excludes_discarded_partial_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [1_800_000_000.0]
    monkeypatch.setattr(
        "ironsbot.core.time.now",
        lambda: datetime.fromtimestamp(clock[0], tz=timezone.utc),
    )

    class Game(_PeakGame):
        async def send_and_wait(
            self, command_id: int, player_id: int, param: int
        ) -> tuple[None, SimpleNamespace]:
            clock[0] += 1
            return await super().send_and_wait(command_id, player_id, param)

    # The first packet succeeded, but its whole mode is discarded after packet 2.
    result = await fetch_unity_peak_partial(
        Game(timeout_param=124802), 712_345_678, timeout_seconds=0.1
    )
    assert result.available_modes == frozenset(("wild", "expert"))
    expected_first_complete_mode_at = 1_800_000_003.0
    assert result.fetched_at == expected_first_complete_mode_at


@pytest.mark.asyncio
async def test_peak_partial_keeps_later_modes_aligned_after_standard_timeout() -> None:
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
