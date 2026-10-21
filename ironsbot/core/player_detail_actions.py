# SPDX-License-Identifier: MIT
"""Shared request value for built-in and separately packaged player actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.core.platform import ActorRef, ConversationRef


@dataclass(frozen=True, slots=True)
class PlayerDetailActionRequest:
    player_id: int
    actor: ActorRef
    conversation: ConversationRef
    can_manage: bool = False
