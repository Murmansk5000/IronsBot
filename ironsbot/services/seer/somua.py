# SPDX-License-Identifier: MIT
"""Verified public Somua score and dedicated leaderboard wire contract."""

from __future__ import annotations

import struct
from itertools import pairwise

from ironsbot.core.seer_ids import is_valid_player_id
from ironsbot.services.seer.rank_models import RankEntry
from ironsbot.services.seer.somua_models import (
    SomuaCommonSlot,
    SomuaParts,
    SomuaRankEntry,
)

SOMUA_SCORE_PARAM = 152801
SOMUA_RANK_COMMAND = 45965
# Cache identity uses the dedicated command and the global-board flag, not 4481.
SOMUA_RANK_KEY = SOMUA_RANK_COMMAND
SOMUA_RANK_SUB_KEY = 1
SOMUA_RANK_PAGE_SIZE = 100
_ENTRY_BYTES = 24
_EXPANDED_ENTRY_BYTES = 144
_COUNT_BYTES = 4


def parse_somua_rank_page(data: bytes, maximum: int) -> list[RankEntry]:
    if len(data) < _COUNT_BYTES:
        raise ValueError("苏摩榜单数据不完整")
    count = struct.unpack_from("!I", data)[0]
    if count > maximum or maximum < 0:
        raise ValueError("苏摩榜单数据长度异常")
    if count == 0:
        if len(data) != _COUNT_BYTES:
            raise ValueError("苏摩榜单数据长度异常")
        return []
    payload_size = len(data) - _COUNT_BYTES
    entry_size, remainder = divmod(payload_size, count)
    if remainder or entry_size not in {_ENTRY_BYTES, _EXPANDED_ENTRY_BYTES}:
        raise ValueError("苏摩榜单数据长度异常")
    result = []
    seen: set[int] = set()
    for index in range(count):
        offset = _COUNT_BYTES + index * entry_size
        player_id, score = struct.unpack_from("!II", data, offset)
        if not is_valid_player_id(player_id) or player_id in seen:
            raise ValueError("苏摩榜单玩家数据异常")
        nick = data[offset + 8 : offset + _ENTRY_BYTES].split(b"\0", 1)[0]
        name = nick.decode("utf-8", errors="replace")
        if entry_size == _EXPANDED_ENTRY_BYTES:
            result.append(
                SomuaRankEntry(player_id, name, score, _common_slots(data, offset))
            )
        else:
            result.append(RankEntry(player_id, name, score))
        seen.add(player_id)
    if any(left.score < right.score for left, right in pairwise(result)):
        raise ValueError("苏摩榜单积分顺序异常")
    return result


def _common_slots(data: bytes, offset: int) -> tuple[SomuaCommonSlot, ...]:
    sequences = struct.unpack_from("!3I", data, offset + _ENTRY_BYTES)
    present = [sequence for sequence in sequences if sequence]
    if len(present) != len(set(present)):
        raise ValueError("苏摩常用实例数据异常")
    parts_start = offset + _ENTRY_BYTES + struct.calcsize("!3I")
    parts_size = struct.calcsize("!9I")
    return tuple(
        SomuaCommonSlot(
            sequence,
            SomuaParts(
                *struct.unpack_from("!9I", data, parts_start + position * parts_size)
            ),
        )
        for position, sequence in enumerate(sequences)
    )
