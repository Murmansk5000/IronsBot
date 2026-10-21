# SPDX-License-Identifier: MIT
"""Poke reply policy over normalized actors and conversations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from random import choice
from typing import TYPE_CHECKING, Protocol

from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT
from ironsbot.core.outbound import OutboundMessage, address_message_to
from ironsbot.services.messaging.rate_limits import SlidingWindowRateLimiter

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from ironsbot.config.models.features import HelpConfig
    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.outbound import SendResult
    from ironsbot.core.platform import ActorRef, ConversationRef


class CommandHintCandidate(Protocol):
    def poke_text(self) -> str: ...


CommandHintCandidates = Callable[
    ["CommandContext", tuple[str, ...]], Sequence[CommandHintCandidate]
]


@dataclass(slots=True)
class PokeReplyService:
    config: HelpConfig
    user_replies: Mapping[ActorRef, str] = field(default_factory=dict)
    group_replies: Mapping[ConversationRef, str] = field(default_factory=dict)
    candidates: CommandHintCandidates | None = None
    chooser: Callable[[Sequence[CommandHintCandidate]], CommandHintCandidate] = choice
    limiter: SlidingWindowRateLimiter = field(default_factory=SlidingWindowRateLimiter)

    def get_configured_reply(self, context: CommandContext) -> str | None:
        return self.user_replies.get(context.actor) or self.group_replies.get(
            context.conversation
        )

    def get_default_reply(self, context: CommandContext) -> str | None:
        if self.candidates is None:
            return None
        candidates = self.candidates(context, tuple(self.config.ignored_plugins))
        if not candidates:
            return None
        return f"{self.chooser(candidates).poke_text()}\n发送“帮助”可查看全部指令。"

    def can_send(
        self, conversation: ConversationRef, *, now: float | None = None
    ) -> bool:
        if conversation.kind == "private":
            return True
        return (
            self.limiter.hit(
                "poke_reply",
                conversation,
                window_seconds=self.config.hint_window_seconds,
                max_events=self.config.hint_max_per_window,
                now=now,
            )
            >= 0
        )

    async def handle(
        self,
        context: CommandContext,
        send: Callable[[OutboundMessage], Awaitable[SendResult]],
        *,
        group_role: Callable[[], Awaitable[str | None]],
    ) -> SendResult | None:
        if not self.can_send(context.conversation):
            return None
        if context.is_group:
            context = replace(context, group_role=await group_role())
        reply = (
            self.get_configured_reply(context)
            or self.get_default_reply(context)
            or DIRECT_COMMAND_HELP_HINT_TEXT
        )
        message = OutboundMessage.from_text(reply)
        if context.is_group:
            message = address_message_to(message, (context.actor,))
        return await send(message)
