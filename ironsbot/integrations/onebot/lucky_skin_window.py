# SPDX-License-Identifier: MIT
"""OneBot configuration adapter for lucky-skin-window subscriptions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    Platform,
)
from ironsbot.services.messaging.subscriptions import PushSubscriptionOption
from ironsbot.services.seer.lucky_skin_window import LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY

if TYPE_CHECKING:
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService


@dataclass(frozen=True, slots=True)
class OneBotLuckySkinWindowSubscriptionOptions:
    """Expose messaging subscription options from OneBot private conversations."""

    service: LuckySkinWindowService
    subscriptions: PushSubscriptionRepository

    def subscription_options(
        self,
        conversation: ConversationRef,
    ) -> list[PushSubscriptionOption]:
        if (
            conversation.platform is not Platform.ONEBOT
            or conversation.kind != "private"
            or not conversation.id.isdecimal()
        ):
            return []
        actor = ActorRef(Platform.ONEBOT, conversation.id)
        if not self.service.is_eligible_actor(actor):
            return []
        return [
            PushSubscriptionOption(
                key=LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
                label="幸运橱窗提醒",
                feature="lucky_skin_window",
                unsubscribed=self.subscriptions.is_unsubscribed(
                    conversation,
                    LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
                ),
            )
        ]
