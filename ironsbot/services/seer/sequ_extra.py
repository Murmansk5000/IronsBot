# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any

from ironsbot.core import time as clock
from ironsbot.core.binary import BufferReader
from ironsbot.core.platform import reference_digest
from ironsbot.core.tasks import OperationDeadline
from ironsbot.core.time import ObservationTime
from ironsbot.services.operations.headless_pool import (
    HeadlessRequestPriority,
    PooledHeadlessGame,
    current_headless_request_priority,
)
from ironsbot.services.seer.observation_cache import CachedObservation
from ironsbot.services.seer.peak_modes import PEAK_MODES, valid_peak_counts

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.seer.observation_cache import ObservationCache

logger = logging.getLogger(__name__)

UNITY_INFO_CMD = 41298
USER_FOREVER_VALUE_CMD = 40002
PEAK_QUERY_DELAY_SECONDS = 0.005
PEAK_PARAMS_BY_MODE = tuple(
    (mode.slug, mode.personal_params) for mode in PEAK_MODES.values()
)
PEAK_PARAMS = tuple(param for _, params in PEAK_PARAMS_BY_MODE for param in params)
PEAK_PERSONAL_SCHEMA = PEAK_PARAMS
PEAK_FIELD_NAMES = ("current", "history", "wins", "matches")


@dataclass(slots=True)
class UnityPartOneInfo:
    achievement_num: int = 0
    pet_kind_num: int = 0
    skin_num: int = 0
    title1: int = 0
    title2: int = 0
    title3: int = 0
    title4: int = 0


@dataclass(slots=True)
class UnityPeakInfo:
    current_j_star: int = 0
    current_j_rank: int = 0
    history_j_star: int = 0
    history_j_rank: int = 0
    current_j_win: int = 0
    current_j_all: int = 0
    current_k_star: int = 0
    current_k_rank: int = 0
    history_k_star: int = 0
    history_k_rank: int = 0
    current_k_win: int = 0
    current_k_all: int = 0
    current_z_score: int = 0
    history_z_score: int = 0
    current_z_win: int = 0
    current_z_all: int = 0
    current_m_star: int = 0
    current_m_rank: int = 0
    history_m_star: int = 0
    history_m_rank: int = 0
    current_m_win: int = 0
    # None denotes unavailable data, not a player with zero matches.
    current_m_all: int | None = None


@dataclass(frozen=True, slots=True)
class PeakField:
    value: int | None = None
    fetched_at: float | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class UnityPeakFetchResult:
    """Partial peak-base response with per-mode availability."""

    info: UnityPeakInfo
    available_modes: frozenset[str]
    mode_errors: tuple[tuple[str, str], ...] = ()
    fetched_at: float | None = None
    fields: dict[tuple[str, str], PeakField] = field(default_factory=dict)

    def modes_with(self, *names: str) -> frozenset[str]:
        if not self.fields:
            return self.available_modes
        return frozenset(
            mode
            for mode, _ in PEAK_PARAMS_BY_MODE
            if all(self.fields[mode, name].value is not None for name in names)
        )

    def error_for(self, mode: str) -> str | None:
        return dict(self.mode_errors).get(mode)


def _read_uint32_or_zero(reader: BufferReader) -> int:
    return reader.read_uint32() if reader.has_remaining(4) else 0


def parse_unity_part_one(data: bytes | bytearray | memoryview) -> UnityPartOneInfo:
    reader = BufferReader(data)
    if reader.has_remaining(12):
        reader.skip(12)
    return UnityPartOneInfo(
        achievement_num=_read_uint32_or_zero(reader),
        pet_kind_num=_read_uint32_or_zero(reader),
        skin_num=_read_uint32_or_zero(reader),
        title1=_read_uint32_or_zero(reader),
        title2=_read_uint32_or_zero(reader),
        title3=_read_uint32_or_zero(reader),
        title4=_read_uint32_or_zero(reader),
    )


def parse_unity_peak(data: bytes | bytearray | memoryview) -> UnityPeakInfo:
    if len(data) != len(PEAK_PARAMS) * 4:
        raise ValueError("巅峰个人数据字段不完整")
    reader = BufferReader(data)
    return UnityPeakInfo(
        current_j_star=reader.read_uint16() if reader.has_remaining(2) else 0,
        current_j_rank=reader.read_uint16() if reader.has_remaining(2) else 0,
        history_j_star=reader.read_uint16() if reader.has_remaining(2) else 0,
        history_j_rank=reader.read_uint16() if reader.has_remaining(2) else 0,
        current_j_win=reader.read_uint32() if reader.has_remaining(4) else 0,
        current_j_all=reader.read_uint32() if reader.has_remaining(4) else 0,
        current_k_star=reader.read_uint16() if reader.has_remaining(2) else 0,
        current_k_rank=reader.read_uint16() if reader.has_remaining(2) else 0,
        history_k_star=reader.read_uint16() if reader.has_remaining(2) else 0,
        history_k_rank=reader.read_uint16() if reader.has_remaining(2) else 0,
        current_k_win=reader.read_uint32() if reader.has_remaining(4) else 0,
        current_k_all=reader.read_uint32() if reader.has_remaining(4) else 0,
        current_z_score=reader.read_uint32() if reader.has_remaining(4) else 0,
        history_z_score=reader.read_uint32() if reader.has_remaining(4) else 0,
        current_z_win=reader.read_uint32() if reader.has_remaining(4) else 0,
        current_z_all=reader.read_uint32() if reader.has_remaining(4) else 0,
        current_m_star=reader.read_uint16() if reader.has_remaining(2) else 0,
        current_m_rank=reader.read_uint16() if reader.has_remaining(2) else 0,
        history_m_star=reader.read_uint16() if reader.has_remaining(2) else 0,
        history_m_rank=reader.read_uint16() if reader.has_remaining(2) else 0,
        current_m_win=reader.read_uint32() if reader.has_remaining(4) else 0,
        current_m_all=reader.read_uint32(),
    )


async def _fetch_unity_part(game: Any, part: int, player_id: int) -> bytes:
    _head, body = await game.send_and_wait(UNITY_INFO_CMD, part, player_id, 0, 0)
    return bytes(body)


async def fetch_unity_part_one(game: Any, player_id: int) -> UnityPartOneInfo:
    return parse_unity_part_one(await _fetch_unity_part(game, 1, player_id))


async def fetch_unity_peak(
    game: Any, player_id: int, *, mode: str | None = None
) -> UnityPeakInfo:
    chunks: list[bytes] = []
    if mode is not None and mode not in dict(PEAK_PARAMS_BY_MODE):
        raise ValueError(mode)
    for name, params in PEAK_PARAMS_BY_MODE:
        for param in params:
            if mode is not None and name != mode:
                chunks.append(struct.pack("!I", 0))
                continue
            _head, body = await game.send_and_wait(
                USER_FOREVER_VALUE_CMD,
                player_id,
                param,
            )
            chunks.append(struct.pack("!I", int(body.value) & 0xFFFFFFFF))
            await asyncio.sleep(PEAK_QUERY_DELAY_SECONDS)
    return parse_unity_peak(b"".join(chunks))


async def fetch_unity_peak_partial(  # noqa: PLR0913
    game: Any,
    player_id: int,
    *,
    timeout_seconds: float,
    observations: ObservationCache | None = None,
    observation_ttl: float = 300,
    season: int | None = None,
) -> UnityPeakFetchResult:
    """Read peak data mode by mode without turning a partial timeout into zeros."""

    deadline = OperationDeadline.after(timeout_seconds)
    results = await asyncio.gather(
        *(
            _read_peak_mode(
                game,
                player_id,
                mode,
                params,
                deadline,
                observations=observations,
                ttl=observation_ttl,
                season=season,
            )
            for mode, params in PEAK_PARAMS_BY_MODE
        )
    )
    chunks: list[bytes] = []
    fields: dict[tuple[str, str], PeakField] = {}
    available_modes: set[str] = set()
    mode_errors: list[tuple[str, str]] = []
    stamp = ObservationTime()
    for (mode, _), values in zip(PEAK_PARAMS_BY_MODE, results, strict=True):
        fields.update(
            zip(((mode, name) for name in PEAK_FIELD_NAMES), values, strict=True)
        )
        chunks.extend(struct.pack("!I", item.value or 0) for item in values)
        for item in values:
            if item.value is not None:
                stamp.include(item.fetched_at)
        error = next((item.error for item in values if item.error), None)
        if error:
            mode_errors.append((mode, error))
        else:
            available_modes.add(mode)
        wins, total = (item.value for item in values[-2:])
        if (
            wins is not None
            and total is not None
            and not valid_peak_counts(wins, total)
        ):
            mode_errors.append((mode, "场次数据异常"))
            if observations is not None:
                params = dict(PEAK_PARAMS_BY_MODE)[mode]
                for param in params[-2:]:
                    observations.discard((player_id, "peak_field", season, mode, param))
    info = parse_unity_peak(b"".join(chunks))
    info.current_m_all = fields["master", "matches"].value
    return UnityPeakFetchResult(
        info, frozenset(available_modes), tuple(mode_errors), stamp.fetched_at, fields
    )


async def _read_peak_mode(  # noqa: PLR0913
    game: Any,
    player_id: int,
    mode: str,
    params: tuple[int, ...],
    deadline: OperationDeadline,
    *,
    observations: ObservationCache | None,
    ttl: float,
    season: int | None,
) -> list[PeakField]:
    values = []
    for name, param in zip(PEAK_FIELD_NAMES, params, strict=True):
        args = (player_id, "peak_field", season, mode, param)
        read = partial(_read_peak_field, game, player_id, param, deadline)
        field = await _observe_peak_field(
            read, args, deadline, observations if season is not None else None, ttl
        )
        if field.error:
            logger.warning(
                "peak base field failed: player_id=%s mode=%s field=%s param=%s "
                "worker_ref=%s error=%s remaining=%.3fs",
                player_id,
                mode,
                name,
                param,
                reference_digest(str(getattr(game, "user_id", "unknown"))),
                field.error,
                deadline.remaining(),
            )
        values.append(field)
        if param != params[-1] and deadline.remaining():
            await asyncio.sleep(deadline.remaining(PEAK_QUERY_DELAY_SECONDS))
    return values


async def _observe_peak_field(
    read: Callable[[], Awaitable[CachedObservation]],
    key: tuple[object, ...],
    deadline: OperationDeadline,
    observations: ObservationCache | None,
    ttl: float,
) -> PeakField:
    cached = observations.get(key, ttl) if observations is not None else None
    if cached is not None:
        return PeakField(cached.value, cached.fetched_at)

    async def load() -> CachedObservation:
        item = await read()
        if observations is not None:
            observations.save(key, item.value, item.fetched_at)
        return item

    background = (
        current_headless_request_priority().priority
        == HeadlessRequestPriority.BACKGROUND
    )
    retry_shared = (
        not background
        and observations is not None
        and observations.inflight_background(key)
    )

    async def attempt() -> PeakField:
        if not deadline.remaining():
            return PeakField(error="查询超时")
        try:
            async with asyncio.timeout(deadline.remaining()):
                item = await (
                    observations.share(key, load, background=background)
                    if observations is not None
                    else load()
                )
            return PeakField(item.value, item.fetched_at)
        except Exception as error:  # noqa: BLE001 - return partial results
            return PeakField(error=_peak_field_error(error))

    result = await attempt()
    if result.error and retry_shared and deadline.remaining():
        return await attempt()
    return result


def _peak_field_error(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "查询超时"
    if isinstance(error, (ValueError, TypeError, AttributeError, struct.error)):
        return "数据格式异常"
    return type(error).__name__


async def _read_peak_field(
    game: Any, player_id: int, param: int, deadline: OperationDeadline
) -> CachedObservation:
    if not deadline.remaining():
        raise TimeoutError
    if isinstance(game, PooledHeadlessGame):
        _head, body = await game.read_peak_field(
            USER_FOREVER_VALUE_CMD, player_id, param, deadline
        )
    else:
        _head, body = await game.send_and_wait(USER_FOREVER_VALUE_CMD, player_id, param)
    if not deadline.remaining():
        raise TimeoutError
    return CachedObservation(int(body.value) & 0xFFFFFFFF, clock.now().timestamp())
