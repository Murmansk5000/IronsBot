# SPDX-License-Identifier: MIT
"""Platform-neutral routing policy for AI chat, intent, and addressed hints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.message_input import MessageInputKind

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandCatalog, CommandContext
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext

_AI_PLUGIN_IDS = ("ai_chat", "ai_intent")


@dataclass(frozen=True, slots=True)
class AiInputDecision:
    """Allowed AI fallbacks after command ownership has been resolved."""

    try_intent: bool = False
    try_chat: bool = False
    offer_help_hint: bool = False

    @property
    def recognized(self) -> bool:
        return self.try_intent or self.try_chat or self.offer_help_hint


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
            return AiInputDecision()

        if self._is_claimed_command(
            message.text,
            command_context,
            normalized_text=normalized_text,
        ):
            return AiInputDecision()

        available = self._available_ai_commands(command_context)
        if message.kind is MessageInputKind.BOT_MENTION:
            chat = "ai_chat.group" in available
            return AiInputDecision(
                try_chat=chat,
                offer_help_hint=not chat,
            )

        if message.kind is not MessageInputKind.DIRECT:
            return AiInputDecision()

        return AiInputDecision(
            try_intent=any(
                command_id.startswith("ai_intent.") for command_id in available
            ),
            try_chat=(
                command_context.conversation.kind == "private"
                and "ai_chat.private" in available
            ),
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
            for command in self._commands.available_for_context(context, self._features)
            if command.plugin_id in _AI_PLUGIN_IDS
        )
