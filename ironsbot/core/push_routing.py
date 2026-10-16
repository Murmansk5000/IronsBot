# SPDX-License-Identifier: MIT
"""Distinguish intentional push-policy skips from unavailable routes."""

from dataclasses import dataclass
from typing import Literal

from ironsbot.core.platform import ConversationRef


@dataclass(frozen=True, slots=True)
class PushRouteDecision:
    status: Literal["ready", "skipped", "unavailable"]
    target: ConversationRef
    reason: str = ""
