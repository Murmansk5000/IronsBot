# SPDX-License-Identifier: MIT
"""Trigger-independent, permission-filtered command recommendations."""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT

if TYPE_CHECKING:
    from ironsbot.config.models.features import HelpConfig
    from ironsbot.core.command_catalog import CommandCatalog, CommandContext
    from ironsbot.core.feature_policy import FeatureService

_LOGGER = logging.getLogger(__name__)
_MANIFEST = (
    Path(__file__).resolve().parents[2] / "_generated/poke_command_introductions.json"
)


def load_introductions(path: Path = _MANIFEST) -> dict[str, datetime]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        valid_schema = raw.get("schema_version") == 1
        introductions = {
            key: datetime.fromisoformat(value.replace("Z", "+00:00"))
            for key, value in raw["commands"].items()
        }
        valid_times = all(value.tzinfo is not None for value in introductions.values())
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        _LOGGER.warning(
            "command introduction manifest unavailable; using uniform weights"
        )
        return {}
    if valid_schema and valid_times:
        return introductions
    _LOGGER.warning("invalid command introduction manifest; using uniform weights")
    return {}


@dataclass(frozen=True, slots=True)
class CommandRecommendationService:
    catalog: CommandCatalog
    features: FeatureService
    config: HelpConfig
    introduced_at: dict[str, datetime] = field(default_factory=load_introductions)

    def weight(self, command_id: str, now: datetime) -> float:
        introduced = self.introduced_at.get(command_id)
        if introduced is None:
            return 1.0
        age = max(0.0, (now - introduced).total_seconds() / 86400)
        return 1 + (self.config.new_command_initial_weight - 1) * (
            0.5 ** (age / self.config.new_command_half_life_days)
        )

    def reply(self, context: CommandContext) -> str:
        candidates = self.catalog.poke_candidates_for_context(
            context, self.features, ignored_plugins=self.config.ignored_plugins
        )
        if not candidates:
            return DIRECT_COMMAND_HELP_HINT_TEXT
        now = datetime.now(timezone.utc)
        selected = random.choices(  # nosec B311 - presentation selection only
            candidates, weights=[self.weight(item.id, now) for item in candidates], k=1
        )[0]
        return selected.poke_text() + "\n发送“帮助”可查看全部指令。"


# TODO: Connect future official poke events to this service without changing policy.
