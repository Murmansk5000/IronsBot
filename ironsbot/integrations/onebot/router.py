# SPDX-License-Identifier: MIT
"""OneBot connection lookup after the shared policy selects an account."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.platform import reference_digest

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ironsbot.core.platform import ConversationRef
    from ironsbot.integrations.onebot.connections import (
        OneBotConnection,
        OneBotConnections,
    )
    from ironsbot.services.onebot_routing import OneBotRoutingPolicy


@dataclass(frozen=True, slots=True)
class BotRouter:
    policy: OneBotRoutingPolicy
    connections: OneBotConnections

    def for_conversation(
        self, conversation: ConversationRef
    ) -> OneBotConnection | None:
        route = self.policy.resolve(conversation)
        if route.bot_id is None:
            logger.info(
                "OneBot target has no configured account: kind=%s ref=%s reason=%s",
                conversation.kind,
                reference_digest(conversation.id),
                route.reason,
            )
            return None
        bot = self.connections.get(str(route.bot_id))
        if bot is None:
            logger.warning(
                "selected OneBot account is not connected: target_type=%s "
                "target_ref=%s bot_ref=%s route=%s; delivery will be skipped",
                conversation.kind,
                reference_digest(conversation.id),
                reference_digest(str(route.bot_id)),
                route.reason,
            )
        return bot
