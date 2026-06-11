# SPDX-License-Identifier: MIT
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ironsbot.shared.config.config import (
    LocalRankConfig,
    PlayerQueryConfig,
    RankQueryConfig,
    RenderConfig,
    TeamConfig,
    TeamQueryConfig,
)


class SeerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player: PlayerQueryConfig = Field(default_factory=PlayerQueryConfig)
    team: TeamQueryConfig = Field(default_factory=TeamQueryConfig)
    rank: RankQueryConfig = Field(default_factory=RankQueryConfig)
    local_rank: LocalRankConfig = Field(default_factory=LocalRankConfig)
    team_shortcut: TeamConfig = Field(default_factory=TeamConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)


__all__ = ["SeerConfig"]
