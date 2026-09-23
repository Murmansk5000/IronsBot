# SPDX-License-Identifier: MIT
"""Platform-neutral message-routing facts produced by transport adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.core.outbound import ExecutionIdentity
    from ironsbot.core.platform import ActorRef, IncomingMessageRef


class MessageInputKind(str, Enum):
    """Routing class evaluated in the declared precedence order."""

    REPLY = "reply"
    BOT_MENTION = "bot_mention"
    MEMBER_MENTION = "member_mention"
    DIRECT = "direct"


@dataclass(frozen=True, slots=True)
class MessageInputContext:
    """Only the newly-sent message, never its quoted message body."""

    message: IncomingMessageRef
    mentions_bot: bool
    automatic_fallback_allowed: bool = True
    execution_identity: ExecutionIdentity | None = None
    mentions_everyone: bool = False

    @property
    def text(self) -> str:
        return self.message.text

    @property
    def is_reply(self) -> bool:
        return self.message.reply_to_id is not None

    @property
    def member_mentions(self) -> tuple[ActorRef, ...]:
        return self.message.direct_mentions

    @property
    def has_any_mention(self) -> bool:
        return self.mentions_bot or self.mentions_everyone or bool(self.member_mentions)

    @property
    def kind(self) -> MessageInputKind:
        if self.is_reply:
            return MessageInputKind.REPLY
        if self.mentions_bot:
            return MessageInputKind.BOT_MENTION
        if self.member_mentions:
            return MessageInputKind.MEMBER_MENTION
        return MessageInputKind.DIRECT

    @property
    def has_member_mentions(self) -> bool:
        return bool(self.member_mentions)
