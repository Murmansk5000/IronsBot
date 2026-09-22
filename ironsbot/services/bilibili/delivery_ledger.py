# SPDX-License-Identifier: MIT
"""At-most-once stage delivery contract, independent of transport and storage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.core.outbound import DeliveryFailureKind, SendResult

if TYPE_CHECKING:
    from ironsbot.core.outbound import (
        DeliveryCapabilities,
        OutboundMessage,
        OutboundMessenger,
        ReplyContext,
    )
    from ironsbot.core.platform import ConversationRef
    from ironsbot.services.bilibili.target_models import BiliPushTargets


class DynamicDeliveryLedger(Protocol):
    def prepare(
        self,
        item: dict[str, Any],
        pub_ts: int,
        uid: int,
        targets: BiliPushTargets,
        categories: tuple[str, ...],
    ) -> bool: ...
    def pending(self) -> list[dict[str, Any]]: ...
    def claim(self, dynamic_id: str, target: ConversationRef, stage: str) -> bool: ...
    def finish(
        self, dynamic_id: str, target: ConversationRef, stage: str, result: SendResult
    ) -> None: ...
    def skip_remaining(self, dynamic_id: str) -> None: ...
    def recover(self) -> None: ...
    def claim_notification(self, dynamic_id: str) -> bool: ...
    def unattempted(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class StageMessenger:
    messenger: OutboundMessenger
    ledger: DynamicDeliveryLedger
    dynamic_id: str
    stage: str

    def capabilities_for(self, conversation: ConversationRef) -> DeliveryCapabilities:
        return self.messenger.capabilities_for(conversation)

    async def send(
        self, conversation: ConversationRef, message: OutboundMessage
    ) -> SendResult:
        if not self.ledger.claim(self.dynamic_id, conversation, self.stage):
            return SendResult(delivered=True, message_id="ledger:already-handled")
        try:
            result = await self.messenger.send(conversation, message)
        except Exception as error:  # noqa: BLE001 - a raised transport result is ambiguous
            result = SendResult(
                delivered=False,
                error_code=type(error).__name__,
                failure_kind=DeliveryFailureKind.UNCERTAIN,
            )
        self.ledger.finish(self.dynamic_id, conversation, self.stage, result)
        return result

    async def reply(
        self, context: ReplyContext, message: OutboundMessage
    ) -> SendResult:
        return await self.send(context.conversation, message)
