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
from ironsbot.services.seer.lucky_skin_window import (
    LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
    LuckySkinWindowAccount,
)

if TYPE_CHECKING:
    from ironsbot.config.models.seer_lucky import LuckySkinWindowConfig
    from ironsbot.config.onebot_references import OneBotReferenceResolver
    from ironsbot.services.identity.player_accounts import PlayerAccountRegistry
    from ironsbot.services.identity_principals import IdentityPrincipalService
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService


@dataclass(frozen=True, slots=True)
class OneBotLuckySkinWindowSubscriptionOptions:
    """Expose messaging subscription options from OneBot private conversations."""

    service: LuckySkinWindowService
    subscriptions: PushSubscriptionRepository
    identity_principals: IdentityPrincipalService | None = None

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
