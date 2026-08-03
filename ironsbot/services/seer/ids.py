# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.core.seer_ids import (
    PLAYER_ID_MAX,
    PLAYER_ID_MIN,
    TEAM_ID_MAX,
    TEAM_ID_MIN,
)
from ironsbot.core.seer_ids import (
    is_valid_player_id as _is_valid_player_id,
)
from ironsbot.core.seer_ids import (
    is_valid_team_id as _is_valid_team_id,
)

PLAYER_ID_ERROR_MESSAGE = (
    f"❌ 米米号无效，请输入 {PLAYER_ID_MIN} ~ {PLAYER_ID_MAX} 之间的数字。"
)
TEAM_ID_ERROR_MESSAGE = (
    f"❌ 战队ID无效，请输入 {TEAM_ID_MIN} ~ {TEAM_ID_MAX} 之间的数字。"
)


def is_valid_player_id(player_id: int) -> bool:
    return _is_valid_player_id(player_id)


def is_valid_team_id(team_id: int) -> bool:
    return _is_valid_team_id(team_id)
