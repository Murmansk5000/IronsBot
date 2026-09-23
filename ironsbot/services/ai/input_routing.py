# SPDX-License-Identifier: MIT
"""Platform-neutral routing policy for AI chat, intent, and addressed hints."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.message_input import MessageInputKind
from ironsbot.core.platform import reference_digest

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandCatalog, CommandContext
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext

_AI_PLUGIN_IDS = ("ai_chat", "ai_intent")
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AiInputDecision:
    """Allowed AI fallbacks after command ownership has been resolved."""

    try_intent: bool = False
    try_chat: bool = False
    offer_addressed_hint: bool = False

    @property
    def recognized(self) -> bool:
        return self.try_intent or self.try_chat or self.offer_addressed_hint


class AiInputRoutingService:
    """Choose one AI fallback policy from normalized message facts."""

    def __init__(
        self,
        features: FeatureService,
        commands: CommandCatalog,
    ) -> None:
        self._features = features
        self._commands = commands

    def decide(
        self,
        message: MessageInputContext,
        command_context: CommandContext,
        *,
        normalized_text: str | None = None,
    ) -> AiInputDecision:
        if (
            self._is_blocked(message)
            or not message.automatic_fallback_allowed
            or message.kind
            in {
                MessageInputKind.REPLY,
                MessageInputKind.MEMBER_MENTION,
            }
        ):
            self._log(message, "blocked_or_ineligible_input")
            return AiInputDecision()

        if self._is_claimed_command(
            message.text,
            command_context,
            normalized_text=normalized_text,
        ):
            self._log(message, "owned_by_command")
            return AiInputDecision()

        available = self._available_ai_commands(command_context)
        if message.kind is MessageInputKind.BOT_MENTION:
            if not message.text.strip():
                return AiInputDecision(offer_addressed_hint=True)
            chat = "ai_chat.group" in available
            self._log(message, "chat_allowed" if chat else "chat_not_authorized")
            return AiInputDecision(
                try_chat=chat,
                offer_addressed_hint=not chat,
            )

        if message.kind is not MessageInputKind.DIRECT:
            return AiInputDecision()

        self._log(
            message,
            "chat_allowed" if "ai_chat.private" in available else "chat_not_authorized",
        )
        return AiInputDecision(
            try_intent=any(
                command_id.startswith("ai_intent.") for command_id in available
            ),
            try_chat=(
                command_context.conversation.kind == "private"
                and "ai_chat.private" in available
            ),
        )

    def _log(self, context: MessageInputContext, reason: str) -> None:
        if not context.mentions_bot and context.message.conversation.kind != "private":
            return
        superuser = self._features.is_actor_superuser(context.message.actor)
        _LOGGER.info(
            "AI input decision: platform=%s account=%s actor=%s scope=%s "
            "superuser=%s reason=%s",
            context.message.platform.value,
            context.execution_identity.account_id
            if context.execution_identity
            else context.message.conversation.account_id,
            reference_digest(context.message.actor.id),
            context.message.conversation.kind,
            superuser,
            reason,
        )

    def _is_blocked(self, context: MessageInputContext) -> bool:
        message = context.message
        return self._features.is_message_blocked(
            message.actor,
            message.conversation,
        )

    def _is_claimed_command(
        self,
        raw_text: str,
        context: CommandContext,
        *,
        normalized_text: str | None,
    ) -> bool:
        texts = (raw_text, normalized_text.strip()) if normalized_text else (raw_text,)
        return any(
            text
            and self._commands.recognizes_direct_input(
                context,
                text,
                ignored_plugins=_AI_PLUGIN_IDS,
            )
            for text in dict.fromkeys(texts)
        )

    def _available_ai_commands(self, context: CommandContext) -> frozenset[str]:
        return frozenset(
            command.id
            for command in self._commands.executable_for_context(
                context,
                self._features,
            )
            if command.plugin_id in _AI_PLUGIN_IDS
        )
