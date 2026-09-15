# SPDX-License-Identifier: MIT
"""Shared typed port for resolving a player reference within a conversation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ironsbot.core.platform import ActorRef, ConversationRef

PlayerReferenceLookup = Callable[[str, ConversationRef], int | None]


@dataclass(frozen=True, slots=True)
class PlayerReferenceChoice:
    player_id: int
    label: str


PlayerReferenceSearch = Callable[
    [str, ActorRef, ConversationRef], tuple[PlayerReferenceChoice, ...]
]
