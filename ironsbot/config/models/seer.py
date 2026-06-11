# SPDX-License-Identifier: MIT
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ironsbot.shared.config.config import (
    LocalRankConfig,
    PlayerQueryConfig,
    RankQueryConfig,
    RenderConfig,
    TeamConfig,
    TeamQueryConfig,
)
from ironsbot.shared.config.parsing import int_list


class TeamShortcutConfig(TeamConfig):
    team_ids: list[int] = Field(default_factory=list)
    resource_users: list[int] = Field(default_factory=list)

    @field_validator("team_ids", "resource_users", mode="before")
    @classmethod
    def normalize_int_lists(cls, value: object) -> object:
        return int_list(value)


class SeerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player: PlayerQueryConfig = Field(default_factory=PlayerQueryConfig)
    team: TeamQueryConfig = Field(default_factory=TeamQueryConfig)
    rank: RankQueryConfig = Field(default_factory=RankQueryConfig)
    local_rank: LocalRankConfig = Field(default_factory=LocalRankConfig)
    team_shortcut: TeamShortcutConfig = Field(default_factory=TeamShortcutConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)


__all__ = ["SeerConfig", "TeamShortcutConfig"]
