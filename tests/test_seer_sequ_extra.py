from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from ironsbot.services.seer.sequ_extra import fetch_unity_peak_partial

_WILD_FIRST_PARAM = 124791
_EXPECTED_STAR = 3
_EXPECTED_RANK = 2
_EXPECTED_MATCHES = 20


class _PeakGame:
    def __init__(self) -> None:
        self.params: list[int] = []

    async def send_and_wait(
        self,
        _command_id: int,
        _player_id: int,
        param: int,
    ) -> tuple[None, SimpleNamespace]:
        self.params.append(param)
        if param == _WILD_FIRST_PARAM:
            await asyncio.Event().wait()
        values = {
            124801: (3 << 16) + 2,
            124802: (4 << 16) + 1,
            124804: 12,
            124805: 20,
            129441: 1200,
            129443: 1500,
            129446: 8,
            129447: 10,
        }
        return None, SimpleNamespace(value=values[param])


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
