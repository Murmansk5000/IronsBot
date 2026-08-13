# SPDX-License-Identifier: MIT
"""Promotion weights for newly introduced poke-help commands."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.core.features import HelpConfig

_LOGGER = logging.getLogger(__name__)
POKE_PROMOTION_BASELINE_COMMIT = "f53f7dae"
_MANIFEST_SCHEMA_VERSION = 1
_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "_generated"
    / "poke_command_introductions.json"
)


class PokeHintCommand(Protocol):
    @property
    def id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class PokePromotionService:
    """Calculate time-decaying selection weights from a build-time manifest."""

    introduced_at: dict[str, datetime]
    initial_weight: float
    half_life_days: float

    @classmethod
    def from_packaged(cls, config: HelpConfig) -> PokePromotionService:
        return cls.from_path(config, _MANIFEST_PATH)

    @classmethod
    def from_path(cls, config: HelpConfig, path: Path) -> PokePromotionService:
        introduced_at = _load_introduced_at(path)
        if introduced_at is None:
            _LOGGER.warning(
                "poke command promotion manifest is unavailable; "
                "using uniform help-hint weights"
            )
            introduced_at = {}
        return cls(
            introduced_at=introduced_at,
            initial_weight=config.poke_new_command_initial_weight,
            half_life_days=config.poke_new_command_half_life_days,
        )

    def weights_for(
        self,
        candidates: Sequence[PokeHintCommand],
        *,
        now: datetime | None = None,
    ) -> tuple[float, ...]:
        current_time = now or datetime.now(timezone.utc)
        return tuple(
            self.weight_for(command.id, now=current_time) for command in candidates
        )

    def weight_for(self, command_id: str, *, now: datetime | None = None) -> float:
        introduced_at = self.introduced_at.get(command_id)
        if introduced_at is None:
            return 1.0
        current_time = now or datetime.now(timezone.utc)
        age_days = max(0.0, (current_time - introduced_at).total_seconds() / 86400)
        return 1.0 + (self.initial_weight - 1.0) * (
            0.5 ** (age_days / self.half_life_days)
        )


def _load_introduced_at(path: Path) -> dict[str, datetime] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not _is_valid_manifest_header(raw):
        return None
    return _parse_introduced_at(raw["commands"])


def _is_valid_manifest_header(raw: object) -> bool:
    return (
        isinstance(raw, dict)
        and raw.get("schema_version") == _MANIFEST_SCHEMA_VERSION
        and raw.get("baseline_commit") == POKE_PROMOTION_BASELINE_COMMIT
        and isinstance(raw.get("commands"), dict)
    )


def _parse_introduced_at(commands: object) -> dict[str, datetime] | None:
    if not isinstance(commands, dict):
        return None
    try:
        introduced_at = {
            command_id: _parse_timestamp(value)
            for command_id, value in commands.items()
        }
    except (TypeError, ValueError):
        return None
    return introduced_at


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError
    return timestamp.astimezone(timezone.utc)
