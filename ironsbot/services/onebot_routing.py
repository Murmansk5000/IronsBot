# SPDX-License-Identifier: MIT
"""One authoritative numeric-account routing policy, independent of NoneBot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ironsbot.core.platform import Platform
from ironsbot.core.push_routing import PushRouteDecision

if TYPE_CHECKING:
    from ironsbot.config.models.transport import OneBotRoutingConfig
    from ironsbot.config.qq_references import QQReferenceResolver
    from ironsbot.core.platform import ConversationRef


@dataclass(frozen=True, slots=True)
class OneBotAccountRoute:
    bot_id: int | None
    reason: Literal[
        "configured",
        "default",
        "invalid_target",
        "unconfigured_target",
        "missing_default_bot",
    ]


@dataclass(frozen=True, slots=True)
class OneBotRoutingPolicy:
    config: OneBotRoutingConfig
    references: QQReferenceResolver
    use_default_for_unconfigured_targets: bool = False

    def account_name(self, account_id: str) -> str:
        return next(
            (
                name
                for name, value in self.config.bot_aliases.items()
                if str(value) == account_id
            ),
            account_id,
        )

    def resolve(self, conversation: ConversationRef) -> OneBotAccountRoute:
        if (
            conversation.platform is not Platform.ONEBOT
            or conversation.kind not in {"private", "group"}
            or not conversation.id.isdecimal()
            or int(conversation.id) <= 0
        ):
            return OneBotAccountRoute(None, "invalid_target")
        if self.config.enabled:
            configured = self._configured_bot_id(conversation)
            if configured is not None:
                return OneBotAccountRoute(configured, "configured")
        if not self.use_default_for_unconfigured_targets:
            return OneBotAccountRoute(None, "unconfigured_target")
        default = (
            self.config.resolve_bot_reference(self.config.default_bot)
            if self.config.default_bot is not None
            else None
        )
        return OneBotAccountRoute(
            default, "default" if default is not None else "missing_default_bot"
        )

    def allows_incoming(self, bot_id: int, conversation: ConversationRef) -> bool:
        if conversation.platform is not Platform.ONEBOT:
            return False
        if conversation.kind != "group":
            return True
        return self.resolve(conversation).bot_id == bot_id

    def allows_outbound(self, conversation: ConversationRef) -> bool:
        return self.resolve(conversation).bot_id is not None

    def push_route(self, conversation: ConversationRef) -> PushRouteDecision:
        route = self.resolve(conversation)
        return PushRouteDecision(
            "ready"
            if route.bot_id is not None
            else "unavailable"
            if route.reason == "missing_default_bot"
            else "skipped",
            conversation,
            "" if route.bot_id is not None else route.reason,
        )

    def _configured_bot_id(self, conversation: ConversationRef) -> int | None:
        if conversation.kind == "group":
            routes = self.config.groups
            resolve = self.references.resolve_group
            section = "groups"
        else:
            routes = self.config.users
            resolve = self.references.resolve_user
            section = "users"
        for target_ref, bot_ref in routes.items():
            if resolve(
                target_ref,
                location=f"bot.onebot.routing.{section}.{target_ref}",
            ) == int(conversation.id):
                return self.config.resolve_bot_reference(bot_ref)
        return None
