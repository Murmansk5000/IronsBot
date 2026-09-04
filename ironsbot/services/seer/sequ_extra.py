# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import logging
import struct
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from ironsbot.core.binary import BufferReader

logger = logging.getLogger("ironsbot.services.seer.peak_diagnostics")

UNITY_INFO_CMD = 41298
USER_FOREVER_VALUE_CMD = 40002
PEAK_QUERY_DELAY_SECONDS = 0.005
PEAK_PARAMS: tuple[int, ...] = (
    124801,
    124802,
    124804,
    124805,
    124791,
    124792,
    124793,
    124794,
    129441,
    129443,
    129446,
    129447,
)
PEAK_PARAMS_BY_MODE: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("standard", PEAK_PARAMS[0:4]),
    ("wild", PEAK_PARAMS[4:8]),
    ("expert", PEAK_PARAMS[8:12]),
)


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


@dataclass(frozen=True, slots=True)
class UnityPeakFetchResult:
    """Partial peak-base response with per-mode availability."""

    info: UnityPeakInfo
    available_modes: frozenset[str]
    mode_errors: tuple[tuple[str, str], ...] = ()
    query_id: str = "-"

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
    )


async def _fetch_unity_part(game: Any, part: int, player_id: int) -> bytes:
    _head, body = await game.send_and_wait(UNITY_INFO_CMD, part, player_id, 0, 0)
    return bytes(body)


async def fetch_unity_part_one(game: Any, player_id: int) -> UnityPartOneInfo:
    return parse_unity_part_one(await _fetch_unity_part(game, 1, player_id))


async def fetch_unity_peak(game: Any, player_id: int) -> UnityPeakInfo:
    query_id = uuid4().hex[:16]
    chunks: list[bytes] = []
    for mode, params in PEAK_PARAMS_BY_MODE:
        for param in params:
            chunks.append(
                await _fetch_peak_value(
                    game,
                    player_id,
                    param,
                    query_id=query_id,
                    mode=mode,
                )
            )
            await asyncio.sleep(PEAK_QUERY_DELAY_SECONDS)
    info = parse_unity_peak(b"".join(chunks))
    logger.info(
        "peak base complete query=%s player_id=%s fields=%s", query_id, player_id, info
    )
    return info


async def _fetch_peak_value(
    game: Any,
    player_id: int,
    param: int,
    *,
    query_id: str,
    mode: str,
) -> bytes:
    started = time.monotonic()
    logger.info(
        "peak field request query=%s player_id=%s mode=%s command=%s param=%s",
        query_id,
        player_id,
        mode,
        USER_FOREVER_VALUE_CMD,
        param,
    )
    try:
        head, body = await game.send_and_wait(USER_FOREVER_VALUE_CMD, player_id, param)
        value = int(body.value) & 0xFFFFFFFF
    except BaseException as error:
        logger.error(  # noqa: TRY400 - avoid logging transport text containing credentials
            "peak field failed query=%s player_id=%s mode=%s param=%s "
            "elapsed=%.3fs error_type=%s",
            query_id,
            player_id,
            mode,
            param,
            time.monotonic() - started,
            type(error).__name__,
        )
        raise
    logger.info(
        "peak field response query=%s player_id=%s mode=%s param=%s "
        "worker=%s elapsed=%.3fs value=%s hex=%08x",
        query_id,
        player_id,
        mode,
        param,
        getattr(head, "user_id", None),
        time.monotonic() - started,
        value,
        value,
    )
    return struct.pack("!I", value)


async def fetch_unity_peak_partial(
    game: Any,
    player_id: int,
    *,
    timeout_seconds: float,
) -> UnityPeakFetchResult:
    """Read peak data mode by mode without turning a partial timeout into zeros."""

    loop = asyncio.get_running_loop()
    query_id = uuid4().hex[:16]
    logger.info(
        "peak base start query=%s player_id=%s mode_timeout_seconds=%s",
        query_id,
        player_id,
        timeout_seconds,
    )
    # Keep every mode in its protocol-defined slot. If an earlier mode times
    # out, compacting later values would reinterpret wild/expert fields as a
    # different mode when the complete structure is parsed below.
    chunks: list[bytes] = [struct.pack("!I", 0)] * len(PEAK_PARAMS)
    available_modes: list[str] = []
    mode_errors: list[tuple[str, str]] = []

    for mode_index, (mode, params) in enumerate(PEAK_PARAMS_BY_MODE):
        # A slow or unavailable mode must not consume the complete peak-stage
        # budget.  Each mode is an independently useful result and later modes
        # should still be queried after an earlier timeout.
        deadline = loop.time() + timeout_seconds
        mode_chunks: list[bytes] = []
        failed_param = params[0]
        try:
            for param in params:
                failed_param = param
                remaining = max(0.0, deadline - loop.time())
                chunk = await asyncio.wait_for(
                    _fetch_peak_value(
                        game,
                        player_id,
                        param,
                        query_id=query_id,
                        mode=mode,
                    ),
                    timeout=remaining,
                )
                mode_chunks.append(chunk)
                await asyncio.sleep(PEAK_QUERY_DELAY_SECONDS)
        except Exception as error:  # noqa: BLE001
            if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
                error_text = "查询超时"
            else:
                error_text = str(error) or type(error).__name__
            logger.error(  # noqa: TRY400 - record type without transport credentials
                "peak base mode failed: query=%s player_id=%s mode=%s param=%s "
                "completed_params=%s error_type=%s",
                query_id,
                player_id,
                mode,
                failed_param,
                params[: len(mode_chunks)],
                type(error).__name__,
            )
            mode_errors.append((mode, error_text))
            continue
        start = mode_index * len(params)
        chunks[start : start + len(params)] = mode_chunks
        available_modes.append(mode)

    info = parse_unity_peak(b"".join(chunks))
    logger.info(
        "peak base complete query=%s player_id=%s available_modes=%s fields=%s",
        query_id,
        player_id,
        available_modes,
        info,
    )
    return UnityPeakFetchResult(
        info=info,
        available_modes=frozenset(available_modes),
        mode_errors=tuple(mode_errors),
        query_id=query_id,
    )
