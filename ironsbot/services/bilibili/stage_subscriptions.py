# SPDX-License-Identifier: MIT
"""Live stage gates and terminal suppression shared by all delivery rounds."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.core.outbound import DeliveryFailureKind
from ironsbot.services.bilibili.preferences import (
    bili_all_subscription_key,
    bili_stage_subscription_key,
)
from ironsbot.services.bilibili.target_models import BiliPushTargets

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.outbound import SendResult
    from ironsbot.core.platform import ConversationRef
    from ironsbot.services.bilibili.delivery_ledger import DynamicDeliveryLedger
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository


@dataclass(slots=True)
class DynamicStagePolicy:
    subscriptions: PushSubscriptionRepository
    ledger: DynamicDeliveryLedger | None
    dynamic_id: str
    uid: int
    categories: tuple[str, ...]
    eligibility: Callable[[ConversationRef, int, str, tuple[str, ...]], bool] | None
    failures: dict[tuple[ConversationRef, str], SendResult]
    suppressed: set[tuple[ConversationRef, str]] = field(default_factory=set)

    def full_targets(self, targets: BiliPushTargets, stage: str) -> BiliPushTargets:
        return BiliPushTargets(
            full_group_conversations=[
                target
                for target in targets.full_group_conversations
                if self.allowed(target, stage)
            ],
            full_private_conversations=[
                target
                for target in targets.full_private_conversations
                if self.allowed(target, stage)
            ],
            link_group_conversations=[],
            link_private_conversations=[],
        )

    def allowed(self, conversation: ConversationRef, stage: str) -> bool:
        if (conversation, stage) in self.suppressed:
            return False
        allowed = (
            self.eligibility is None
            or self.eligibility(conversation, self.uid, stage, self.categories)
        ) and not any(
            self.subscriptions.is_unsubscribed(conversation, key)
            for key in (
                bili_all_subscription_key(stage),
                bili_stage_subscription_key(self.uid, stage),
            )
        )
        if not allowed:
            self.suppressed.add((conversation, stage))
            if self.ledger is not None:
                self.ledger.skip_stage(self.dynamic_id, conversation, stage)
            for key, result in tuple(self.failures.items()):
                if (
                    key[0] == conversation
                    and key[1].split(":")[0] == stage
                    and result.failure_kind
                    in {
                        DeliveryFailureKind.RETRYABLE,
                        DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
                    }
                ):
                    self.failures.pop(key)
        return allowed
