# SPDX-License-Identifier: MIT
"""Typed scheduled-message recipients shared by config and business services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.core.platform import ActorRef, ConversationRef


@dataclass(frozen=True, slots=True)
class MessageScheduleTargets:
    """Recipients compiled from configured scheduled-message targets."""

    group_mentions: tuple[tuple[ActorRef, ...], ...]
    group_targets: tuple[tuple[ConversationRef, ...], ...] = ()

    def mentions_for(self, index: int) -> tuple[ActorRef, ...]:
        if index < 1 or index > len(self.group_mentions):
            return ()
        return self.group_mentions[index - 1]

    def groups_for(self, index: int) -> tuple[ConversationRef, ...]:
        if index < 1 or index > len(self.group_targets):
            return ()
        return self.group_targets[index - 1]
