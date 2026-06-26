# SPDX-License-Identifier: GPL-3.0-or-later
from ironsbot.config import AppConfig, get_app_config
from ironsbot.config.models.seer import (
    PLAYER_SECTION_KEYS,
    TEAM_SECTION_KEYS,
    LocalRankConfig,
    MintmarkQueryConfig,
    PlayerQueryConfig,
    RankQueryConfig,
    SeerConfig,
    TeamQueryConfig,
)

Config = AppConfig


def get_seer_config() -> SeerConfig:
    return get_app_config().seer


def get_player_query_config() -> PlayerQueryConfig:
    return get_seer_config().player


def get_team_query_config() -> TeamQueryConfig:
    return get_seer_config().team


def get_mintmark_query_config() -> MintmarkQueryConfig:
    return get_seer_config().mintmark


def get_rank_query_config() -> RankQueryConfig:
    return get_seer_config().rank


def get_local_rank_config() -> LocalRankConfig:
    return get_seer_config().local_rank

__all__ = [
    "PLAYER_SECTION_KEYS",
    "TEAM_SECTION_KEYS",
    "Config",
    "LocalRankConfig",
    "MintmarkQueryConfig",
    "PlayerQueryConfig",
    "RankQueryConfig",
    "TeamQueryConfig",
    "get_local_rank_config",
    "get_mintmark_query_config",
    "get_player_query_config",
    "get_rank_query_config",
    "get_seer_config",
    "get_team_query_config",
]
