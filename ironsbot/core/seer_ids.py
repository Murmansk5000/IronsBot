# SPDX-License-Identifier: MIT
"""Stable Seer identifier ranges shared by configuration and query services."""

from __future__ import annotations

PLAYER_ID_MIN = 50_000
PLAYER_ID_MAX = 2_000_000_000
TEAM_ID_MIN = 100_000
TEAM_ID_MAX = 2_000_000_000


def is_valid_player_id(player_id: int) -> bool:
    return PLAYER_ID_MIN <= player_id <= PLAYER_ID_MAX


def is_valid_team_id(team_id: int) -> bool:
    return TEAM_ID_MIN <= team_id <= TEAM_ID_MAX
