# SPDX-License-Identifier: MIT
from collections.abc import Mapping
from dataclasses import dataclass

from ironsbot.config.models.ai import AiConfig


@dataclass(frozen=True, slots=True)
class AiResources:
    config: AiConfig
    api_key: str
    group_aliases: Mapping[str, int]
    team_resource_commands: tuple[str, ...]
    team_resource_timeout_seconds: float
