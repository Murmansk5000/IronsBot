# SPDX-License-Identifier: MIT
"""Explicit capabilities passed to separately distributed extension factories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.core.schedule_rendering import ScheduleRendererRegistry
    from ironsbot.extensions.contracts import PlayerLineupExtensionContext


@dataclass(frozen=True, slots=True)
class ExtensionServices:
    player_lineup: PlayerLineupExtensionContext
    scheduled_messages: ScheduleRendererRegistry
