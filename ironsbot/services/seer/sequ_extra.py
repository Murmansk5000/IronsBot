# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import logging
import struct
from dataclasses import dataclass
from typing import Any

from ironsbot.core.binary import BufferReader
from ironsbot.core.platform import reference_digest
from ironsbot.core.tasks import OperationDeadline
from ironsbot.core.time import ObservationTime
from ironsbot.services.seer.peak_modes import PEAK_MODES

logger = logging.getLogger(__name__)

UNITY_INFO_CMD = 41298
USER_FOREVER_VALUE_CMD = 40002
PEAK_QUERY_DELAY_SECONDS = 0.005
PEAK_PARAMS_BY_MODE = tuple(
    (mode.slug, mode.personal_params) for mode in PEAK_MODES.values()
)
PEAK_PARAMS = tuple(param for _, params in PEAK_PARAMS_BY_MODE for param in params)


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
    # No public per-player match-count field has been verified yet. None must
    # never be interpreted as zero matches or used to publish a win rate.
    current_m_all: int | None = None


@dataclass(frozen=True, slots=True)
class UnityPeakFetchResult:
    """Partial peak-base response with per-mode availability."""

    info: UnityPeakInfo
    available_modes: frozenset[str]
    mode_errors: tuple[tuple[str, str], ...] = ()
    fetched_at: float | None = None

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


async def fetch_unity_peak_partial(
    game: Any,
    player_id: int,
    *,
    timeout_seconds: float,
) -> UnityPeakFetchResult:
    """Read peak data mode by mode without turning a partial timeout into zeros."""

    deadline = OperationDeadline.after(timeout_seconds)
    # Keep every mode in its protocol-defined slot. If an earlier mode times
    # out, compacting later values would reinterpret wild/expert fields as a
    # different mode when the complete structure is parsed below.
    chunks: list[bytes] = [struct.pack("!I", 0)] * len(PEAK_PARAMS)
    available_modes: list[str] = []
    mode_errors: list[tuple[str, str]] = []
    observation = ObservationTime()

    start = 0
    for mode_index, (mode, params) in enumerate(PEAK_PARAMS_BY_MODE):
        # Share the remaining stage budget; an early failure cannot take every
        # later mode's turn, and fast modes leave their unused time available.
        remaining_modes = len(PEAK_PARAMS_BY_MODE) - mode_index
        mode_deadline = OperationDeadline.after(deadline.remaining() / remaining_modes)
        mode_chunks: list[bytes] = []
        mode_observation = ObservationTime()
        failed_param = params[0]
        try:
            for param in params:
                failed_param = param
                remaining = mode_deadline.remaining()
                _head, body = await asyncio.wait_for(
                    mode_observation.observe(
                        lambda param=param: game.send_and_wait(
                            USER_FOREVER_VALUE_CMD, player_id, param
                        )
                    ),
                    timeout=remaining,
                )
                mode_chunks.append(struct.pack("!I", int(body.value) & 0xFFFFFFFF))
                if param != params[-1]:
                    await asyncio.sleep(
                        mode_deadline.remaining(PEAK_QUERY_DELAY_SECONDS)
                    )
        except Exception as error:  # noqa: BLE001
            if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
                error_text = "查询超时"
            else:
                error_text = str(error) or type(error).__name__
            logger.warning(
                "peak base mode failed: player_id=%s mode=%s param=%s "
                "worker_ref=%s error=%s",
                player_id,
                mode,
                failed_param,
                reference_digest(str(getattr(game, "user_id", "unknown"))),
                error_text,
            )
            mode_errors.append((mode, error_text))
            start += len(params)
            continue
        chunks[start : start + len(params)] = mode_chunks
        start += len(params)
        available_modes.append(mode)
        observation.include(mode_observation.fetched_at)

    return UnityPeakFetchResult(
        info=parse_unity_peak(b"".join(chunks)),
        available_modes=frozenset(available_modes),
        mode_errors=tuple(mode_errors),
        fetched_at=observation.fetched_at,
    )
