# SPDX-License-Identifier: MIT
"""Rate-limit fallback hints for messages explicitly addressed to the bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT
from ironsbot.services.messaging.rate_limits import SlidingWindowRateLimiter

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.messaging.command_recommendations import (
        CommandRecommendationService,
    )


@dataclass(slots=True)
class AddressedInputHintService:
    """Admit only a bounded number of hints per actor and conversation."""

    window_seconds: float = 60.0
    max_per_window: int = 3
    limiter: SlidingWindowRateLimiter = field(default_factory=SlidingWindowRateLimiter)
    recommendations: CommandRecommendationService | None = None

    def reply(self, context: CommandContext) -> str:
        if self.recommendations is None:
            return DIRECT_COMMAND_HELP_HINT_TEXT
        return self.recommendations.reply(context)

    def admit(
        self,
        context: MessageInputContext,
        *,
        now: float | None = None,
    ) -> bool:
        message = context.message
        return (
            self.limiter.hit(
                "addressed_input_hint",
                (message.actor, message.conversation),
                window_seconds=self.window_seconds,
                max_events=self.max_per_window,
                now=now,
            )
            >= 0
        )
