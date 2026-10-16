from __future__ import annotations

import asyncio
import struct
from types import SimpleNamespace

import pytest

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.core.time import now
from ironsbot.services.seer.observation_cache import ObservationCache
from ironsbot.services.seer.peak_modes import PEAK_MODE_NAMES
from ironsbot.services.seer.sequ_extra import (
    PEAK_PARAMS,
    fetch_unity_peak_partial,
    parse_unity_peak,
)

PLAYER = 700001001
SEASON = 20261016
MASTER_PARAMS = (408302, 408303, 408306, 408307)
MASTER_MATCHES = 16
EXPERT_MATCHES = 12


class Game:
    def __init__(self, fail: int | None = None) -> None:
        self.calls: list[int] = []
        self.fail = fail

    async def send_and_wait(
        self, _command: int, _player: int, param: int
    ) -> tuple[None, SimpleNamespace]:
        self.calls.append(param)
        await asyncio.sleep(0)
        if param == self.fail:
            raise TimeoutError
        values = dict(zip(PEAK_PARAMS, range(1, len(PEAK_PARAMS) + 1), strict=True))
        return None, SimpleNamespace(value=values[param])


@pytest.fixture(autouse=True)
def no_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ironsbot.services.seer.sequ_extra.PEAK_QUERY_DELAY_SECONDS", 0)


@pytest.mark.parametrize("length", [0, 12, 15, 17])
def test_incomplete_or_extra_personal_fields_are_rejected(length: int) -> None:
    with pytest.raises(ValueError, match="字段不完整"):
        parse_unity_peak(struct.pack(f"!{length}I", *([0] * length)))


def test_four_modes_keep_their_exact_protocol_slots() -> None:
    info = parse_unity_peak(struct.pack("!16I", *range(1, 17)))
    assert (
        info.current_j_all,
        info.current_k_all,
        info.current_z_score,
        info.current_z_all,
        info.current_m_rank,
        info.history_m_rank,
        info.current_m_win,
        info.current_m_all,
    ) == (4, 8, 9, 12, 13, 14, 15, 16)


@pytest.mark.asyncio
async def test_old_master_cache_does_not_poison_other_modes_or_new_data() -> None:
    cache = ObservationCache()
    stamp = now().timestamp()
    for mode in ("standard", "wild", "expert"):
        cache.save(
            (PLAYER, "peak_mode", mode, SEASON), [struct.pack("!I", 0)] * 4, stamp
        )
    cache.save((PLAYER, "peak_mode", "master", SEASON), [b"\0" * 4] * 3, stamp)
    game = Game()
    result = await fetch_unity_peak_partial(
        game, PLAYER, timeout_seconds=2, observations=cache, season=SEASON
    )
    assert result.available_modes == PEAK_MODE_NAMES
    assert tuple(game.calls) == MASTER_PARAMS
    assert result.info.current_m_all == MASTER_MATCHES
    game.calls.clear()
    await fetch_unity_peak_partial(
        game, PLAYER, timeout_seconds=2, observations=cache, season=SEASON
    )
    assert game.calls == []
    await fetch_unity_peak_partial(
        game, PLAYER, timeout_seconds=2, observations=cache, season=SEASON + 1
    )
    assert tuple(game.calls) == PEAK_PARAMS


@pytest.mark.asyncio
async def test_missing_master_total_is_unavailable_and_not_cached() -> None:
    game = Game(fail=408307)
    cache = ObservationCache()
    result = await fetch_unity_peak_partial(
        game, PLAYER, timeout_seconds=2, observations=cache, season=SEASON
    )
    assert "master" not in result.available_modes
    assert result.info.current_m_all is None
    assert result.error_for("master") == "查询超时"
    assert (
        cache.get((PLAYER, "peak_mode", "master", SEASON, MASTER_PARAMS), 300) is None
    )
    assert result.info.current_z_all == EXPERT_MATCHES


@pytest.mark.asyncio
async def test_concurrent_reads_share_each_mode() -> None:
    cache = ObservationCache(TaskOwner().create)
    game = Game()
    results = await asyncio.gather(
        *(
            fetch_unity_peak_partial(
                game, PLAYER, timeout_seconds=2, observations=cache, season=SEASON
            )
            for _ in range(2)
        )
    )
    assert all(result.available_modes == PEAK_MODE_NAMES for result in results)
    assert tuple(game.calls) == PEAK_PARAMS


@pytest.mark.asyncio
async def test_invalid_counts_keep_personal_rating_but_are_not_cached() -> None:
    class InvalidGame(Game):
        async def send_and_wait(
            self, command: int, player: int, param: int
        ) -> tuple[None, SimpleNamespace]:
            header, body = await super().send_and_wait(command, player, param)
            if param == MASTER_PARAMS[-1]:
                body.value = 1
            return header, body

    cache = ObservationCache()
    result = await fetch_unity_peak_partial(
        InvalidGame(), PLAYER, timeout_seconds=2, observations=cache, season=SEASON
    )
    assert "master" in result.available_modes
    assert result.info.current_m_rank == 13  # noqa: PLR2004
    assert result.error_for("master") == "场次数据异常"
    assert (
        cache.get((PLAYER, "peak_mode", "master", SEASON, MASTER_PARAMS), 300) is None
    )
