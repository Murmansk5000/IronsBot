# SPDX-License-Identifier: MIT
"""Transport delivery identities, distinct from semantic business requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.platform import Platform


@dataclass(frozen=True, slots=True)
class InboundMessageKey:
    platform: Platform
    account_id: str
    conversation_kind: str
    conversation_id: str
    message_id: str

    @classmethod
    def from_context(cls, context: MessageInputContext) -> InboundMessageKey:
        incoming = context.message
        return cls(
            incoming.platform,
            context.request_bot_id,
            incoming.conversation.kind,
            incoming.conversation.id,
            incoming.message_id,
        )


class InboundMessageClaims(Protocol):
    async def claim(self, key: InboundMessageKey) -> bool:
        """Atomically reject replayed delivery, not record business success."""
        ...
