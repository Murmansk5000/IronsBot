# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import struct
from dataclasses import dataclass
from typing import Any

from ironsbot.services.seer.binary import BufferReader

UNITY_INFO_CMD = 41298
USER_FOREVER_VALUE_CMD = 40002
PEAK_QUERY_DELAY_SECONDS = 0.005
DISPLAY_PET_COUNT = 4
DISPLAY_PET_BLOCK_PADDING = 132
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
class UnityPartTwoInfo:
    show_pet1: int = 0
    show_pet2: int = 0
    show_pet3: int = 0
    show_pet4: int = 0

    @property
    def show_pets(self) -> tuple[int, int, int, int]:
        return (self.show_pet1, self.show_pet2, self.show_pet3, self.show_pet4)


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


def parse_unity_part_two(data: bytes | bytearray | memoryview) -> UnityPartTwoInfo:
    reader = BufferReader(data)
    if reader.has_remaining(12):
        reader.skip(12)

    pet_ids: list[int] = []
    for index in range(DISPLAY_PET_COUNT):
        if not reader.has_remaining(4):
            break
        pet_ids.append(reader.read_uint32())
        if index < DISPLAY_PET_COUNT - 1 and reader.has_remaining(
            DISPLAY_PET_BLOCK_PADDING
        ):
            reader.skip(DISPLAY_PET_BLOCK_PADDING)

    pet_ids.extend([0] * (DISPLAY_PET_COUNT - len(pet_ids)))
    return UnityPartTwoInfo(*pet_ids[:DISPLAY_PET_COUNT])


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


async def fetch_unity_part_two(game: Any, player_id: int) -> UnityPartTwoInfo:
    return parse_unity_part_two(await _fetch_unity_part(game, 5, player_id))


async def fetch_unity_peak(game: Any, player_id: int) -> UnityPeakInfo:
    chunks: list[bytes] = []
    for param in PEAK_PARAMS:
        _head, body = await game.send_and_wait(
            USER_FOREVER_VALUE_CMD,
            player_id,
            param,
        )
        chunks.append(struct.pack("!I", int(body.value) & 0xFFFFFFFF))
        await asyncio.sleep(PEAK_QUERY_DELAY_SECONDS)
    return parse_unity_peak(b"".join(chunks))
