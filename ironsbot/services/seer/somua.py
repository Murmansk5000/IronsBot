# SPDX-License-Identifier: MIT
"""Verified public Somua score and dedicated leaderboard wire contract."""

from __future__ import annotations

import struct
from itertools import pairwise

from ironsbot.core.seer_ids import is_valid_player_id
from ironsbot.services.seer.rank_models import RankEntry

SOMUA_SCORE_PARAM = 152801
SOMUA_RANK_COMMAND = 45965
# Cache identity uses the dedicated command and the global-board flag, not 4481.
SOMUA_RANK_KEY = SOMUA_RANK_COMMAND
SOMUA_RANK_SUB_KEY = 1
SOMUA_RANK_LIMIT = 1000
SOMUA_RANK_PAGE_SIZE = 100
_ENTRY_BYTES = 24
_COUNT_BYTES = 4


def parse_somua_rank_page(data: bytes, maximum: int) -> list[RankEntry]:
    if len(data) < _COUNT_BYTES:
        raise ValueError("苏摩榜单数据不完整")
    count = struct.unpack_from("!I", data)[0]
    if count > maximum or len(data) != 4 + count * _ENTRY_BYTES:
        raise ValueError("苏摩榜单数据长度异常")
    result = []
    seen: set[int] = set()
    for index in range(count):
        offset = 4 + index * _ENTRY_BYTES
        player_id, score = struct.unpack_from("!II", data, offset)
        if not is_valid_player_id(player_id) or player_id in seen:
            raise ValueError("苏摩榜单玩家数据异常")
        nick = data[offset + 8 : offset + _ENTRY_BYTES].split(b"\0", 1)[0]
        result.append(
            RankEntry(player_id, nick.decode("utf-8", errors="replace"), score)
        )
        seen.add(player_id)
    if any(left.score < right.score for left, right in pairwise(result)):
        raise ValueError("苏摩榜单积分顺序异常")
    return result
