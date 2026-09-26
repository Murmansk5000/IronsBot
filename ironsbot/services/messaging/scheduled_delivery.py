# SPDX-License-Identifier: MIT
"""Platform-neutral delivery contract for configured message schedules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ironsbot.core.platform import ActorRef, ConversationRef


@dataclass(frozen=True, slots=True)
class ScheduledMessageDelivery:
    """One ordered configured text push, addressed through typed references."""

    messages: tuple[str, ...]
    private_conversations: tuple[ConversationRef, ...]
    group_conversations: tuple[ConversationRef, ...]
    group_mentions: tuple[ActorRef, ...]
    action_name: str
    subscription_key: str
    unresolved_mentions_as_text: bool = False
    mention_fallback_name: str = ""


class ScheduledMessageSender(Protocol):
    async def send(self, delivery: ScheduledMessageDelivery) -> None: ...
