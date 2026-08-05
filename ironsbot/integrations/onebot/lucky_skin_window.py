# SPDX-License-Identifier: MIT
"""OneBot adapters for lucky-skin-window notifications and subscriptions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    Platform,
    private_conversation_for_actor,
)
from ironsbot.integrations.onebot.target_refs import is_onebot_private_actor
from ironsbot.integrations.onebot.targets import OneBotMessageTarget
from ironsbot.services.messaging.subscriptions import PushSubscriptionOption
from ironsbot.services.seer.lucky_skin_window import (
    LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
    LuckySkinWindowAccount,
)

if TYPE_CHECKING:
    from ironsbot.config.models.seer import LuckySkinWindowConfig
    from ironsbot.config.onebot_references import OneBotReferenceResolver
    from ironsbot.integrations.onebot.delivery import OneBotDelivery
    from ironsbot.services.identity.player_accounts import PlayerAccountRegistry
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService


@dataclass(frozen=True, slots=True)
class OneBotLuckySkinWindowNotificationSender:
    """Preserve the existing OneBot delivery and unsubscribe behaviour."""

    delivery: OneBotDelivery
    subscriptions: PushSubscriptionRepository

    async def send_daily_notice(
        self,
        actor: ActorRef,
        message: str,
        *,
        day: str,
    ) -> bool:
        if not is_onebot_private_actor(actor):
            return False
        user_id = int(actor.id)
        conversation = private_conversation_for_actor(actor)
        if self.subscriptions.is_unsubscribed(
            conversation,
            LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
        ):
            return False
        if not self.subscriptions.mark_daily_hint_sent(
            conversation,
            "lucky_skin_window_delivery",
            today=day,
        ):
            return False
        summary = await self.delivery.send_targets(
            [OneBotMessageTarget("private", user_id)],
            message,
            action_name="lucky skin window daily notice",
            interval_seconds=0,
            subscription_key=LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
        )
        return bool(summary.succeeded)


@dataclass(frozen=True, slots=True)
class OneBotLuckySkinWindowSubscriptionOptions:
    """Expose legacy messaging settings from typed OneBot actor references."""

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


def build_onebot_lucky_skin_window_accounts(
    config: LuckySkinWindowConfig,
    references: OneBotReferenceResolver,
    player_accounts: PlayerAccountRegistry,
) -> tuple[LuckySkinWindowAccount, ...]:
    """Resolve OneBot-only TOML references before the service is composed."""

    return tuple(
        LuckySkinWindowAccount(
            actor=ActorRef(
                Platform.ONEBOT,
                str(
                    references.resolve_user(
                        configured.user,
                        location=(f"seer.lucky_skin_window.accounts[{index}].user"),
                    )
                ),
            ),
            player_account=player_accounts.resolve(
                configured.account,
                location=(f"seer.lucky_skin_window.accounts[{index}].account"),
            ),
            watched_skin_ids=tuple(configured.watched_skin_ids),
        )
        for index, configured in enumerate(config.accounts)
    )
