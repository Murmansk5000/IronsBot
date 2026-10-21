# SPDX-License-Identifier: MIT
"""At-most-once stage delivery contract, independent of transport and storage."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.core.delivery_attempt import delivery_round, delivery_unit
from ironsbot.core.outbound import DeliveryFailureKind, SendResult
from ironsbot.core.platform import reference_digest

if TYPE_CHECKING:
    from ironsbot.core.outbound import (
        DeliveryCapabilities,
        OutboundMessage,
        OutboundMessenger,
        ReplyContext,
    )
    from ironsbot.core.platform import ConversationRef
    from ironsbot.services.bilibili.target_models import BiliPushTargets

_LOGGER = logging.getLogger(__name__)


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
    def skip_remaining(self, dynamic_id: str) -> bool: ...
    def recover(self) -> None: ...
    def claim_notification(self, dynamic_id: str) -> bool: ...
    def unattempted(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> bool: ...
    def freeze_media(
        self, dynamic_id: str, message: OutboundMessage | None
    ) -> OutboundMessage | None: ...
    def load_media(self, dynamic_id: str) -> tuple[bool, OutboundMessage | None]: ...
    def image_units(
        self, dynamic_id: str, target: ConversationRef, count: int
    ) -> None: ...
    def retry_delay(self, dynamic_id: str) -> float | None: ...
    def attempts(self, dynamic_id: str, target: ConversationRef, stage: str) -> int: ...
    def failures(
        self, dynamic_id: str
    ) -> list[tuple[ConversationRef, str, SendResult]]: ...
    def round_count(self, dynamic_id: str) -> int: ...
    def completed_round_count(self, dynamic_id: str) -> int: ...
    def begin_round(self, dynamic_id: str) -> bool: ...
    def finish_round(self, dynamic_id: str) -> None: ...
    def state_counts(self, dynamic_id: str) -> dict[str, int]: ...


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
            _LOGGER.info(
                "Bilibili unit skipped: dynamic=%s unit=%s round=%d "
                "target=%s reason=ledger_not_claimed",
                self.dynamic_id,
                self.stage,
                delivery_round.get(),
                reference_digest(conversation.id),
            )
            return SendResult(
                delivered=False,
                error_code="ledger:not-claimed",
                attempted=False,
                failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
            )
        token = delivery_unit.set(
            f"dynamic={self.dynamic_id} unit={self.stage} round={delivery_round.get()} "
            f"account={conversation.account_id or '-'} "
            f"target={reference_digest(conversation.id)}"
        )
        started = time.monotonic()
        attempt = self.ledger.attempts(self.dynamic_id, conversation, self.stage)
        _LOGGER.info(
            "Bilibili unit started: %s attempt=%d platform=%s kind=%s",
            delivery_unit.get(),
            attempt,
            conversation.platform.value,
            conversation.kind,
        )
        try:
            result = await self.messenger.send(conversation, message)
        except Exception as error:  # noqa: BLE001 - a raised transport result is ambiguous
            result = SendResult(
                delivered=False,
                error_code=type(error).__name__,
                failure_kind=DeliveryFailureKind.UNCERTAIN,
            )
        finally:
            delivery_unit.reset(token)
        result = replace(
            result,
            attempt_count=self.ledger.attempts(
                self.dynamic_id, conversation, self.stage
            ),
        )
        self.ledger.finish(self.dynamic_id, conversation, self.stage, result)
        if result.delivered:
            _LOGGER.info(
                "Bilibili unit delivered: dynamic=%s unit=%s round=%d target=%s "
                "account=%s attempt=%d elapsed_ms=%d receipt=%s",
                self.dynamic_id,
                self.stage,
                delivery_round.get(),
                reference_digest(conversation.id),
                result.execution_identity.describe()
                if result.execution_identity
                else "unknown",
                result.attempt_count,
                int((time.monotonic() - started) * 1000),
                reference_digest(result.message_id or ""),
            )
        if not result.delivered and result.attempted:
            _LOGGER.warning(
                "Bilibili unit failed: dynamic=%s unit=%s target=%s "
                "account=%s attempt=%d elapsed_ms=%d code=%s "
                "trace_id=%s kind=%s round=%d",
                self.dynamic_id,
                self.stage,
                reference_digest(conversation.id),
                result.execution_identity.describe()
                if result.execution_identity
                else "unknown",
                result.attempt_count,
                int((time.monotonic() - started) * 1000),
                result.error_code,
                result.trace_id,
                result.failure_kind,
                delivery_round.get(),
            )
        return result

    async def reply(
        self, context: ReplyContext, message: OutboundMessage
    ) -> SendResult:
        return await self.send(context.conversation, message)
