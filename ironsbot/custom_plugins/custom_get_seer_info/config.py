# SPDX-License-Identifier: GPL-3.0-or-later
from ironsbot.shared.config.config import (
    PLAYER_SECTION_KEYS,
    TEAM_SECTION_KEYS,
    Config,
    LocalRankConfig,
    PlayerQueryConfig,
    RankQueryConfig,
    SeerQueryConfig,
    TeamQueryConfig,
    get_shared_config,
)

plugin_config = get_shared_config()

__all__ = [
    "PLAYER_SECTION_KEYS",
    "TEAM_SECTION_KEYS",
    "Config",
    "LocalRankConfig",
    "PlayerQueryConfig",
    "RankQueryConfig",
    "SeerQueryConfig",
    "TeamQueryConfig",
    "plugin_config",
]
