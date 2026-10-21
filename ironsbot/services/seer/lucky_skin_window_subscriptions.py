# SPDX-License-Identifier: MIT
"""Shared lucky-window subscription options for the selected private route."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    Platform,
    private_conversation_for_actor,
)
from ironsbot.services.messaging.subscription_options import timed_subscription_label
from ironsbot.services.messaging.subscriptions import PushSubscriptionOption
from ironsbot.services.seer.lucky_skin_window import (
    LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
)

if TYPE_CHECKING:
    from ironsbot.services.identity_principals import IdentityPrincipalService
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository
    from ironsbot.services.private_conversation_routes import PrivateConversationRoutes
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService


@dataclass(frozen=True, slots=True)
class LuckySkinWindowSubscriptionOptions:
    """Expose subscriptions only in the selected private delivery conversation."""

    service: LuckySkinWindowService
    subscriptions: PushSubscriptionRepository
    identity_principals: IdentityPrincipalService | None = None
    private_routes: PrivateConversationRoutes | None = None

    def subscription_options(
        self,
        conversation: ConversationRef,
    ) -> list[PushSubscriptionOption]:
        if conversation.kind != "private":
            return []
        if conversation.platform is Platform.ONEBOT:
            if not conversation.id.isdecimal():
                return []
            actor = ActorRef(Platform.ONEBOT, conversation.id)
        elif self.identity_principals is not None:
            actor = self.identity_principals.onebot_actor(
                ActorRef(
                    Platform.QQ_OFFICIAL,
                    conversation.id,
                    account_id=conversation.account_id,
                )
            )
            if actor is None:
                return []
        else:
            return []
        if not self.service.is_eligible_actor(actor) or (
            self.private_routes is not None
            and self.private_routes.selected_for(private_conversation_for_actor(actor))
            != conversation
        ):
            return []
        return [
            PushSubscriptionOption(
                key=LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
                label=timed_subscription_label(
                    "幸运橱窗提醒",
                    self.service.config.time,
                    timezone=self.service.config.timezone,
                ),
                feature="lucky_skin_window",
                unsubscribed=self.subscriptions.is_unsubscribed(
                    conversation,
                    LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
                ),
            )
        ]
