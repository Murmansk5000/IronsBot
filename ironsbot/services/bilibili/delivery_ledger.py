# SPDX-License-Identifier: MIT
"""At-most-once stage delivery contract, independent of transport and storage."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.core.delivery_attempt import (
    DeliveryProgress,
    delivery_progress,
    delivery_round,
    delivery_unit,
)
from ironsbot.core.outbound import DeliveryFailureKind, SendResult
from ironsbot.core.platform import reference_digest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ironsbot.core.outbound import (
        DeliveryCapabilities,
        OutboundMessage,
        OutboundMessenger,
        ReplyContext,
    )
    from ironsbot.core.platform import ConversationRef
    from ironsbot.services.bilibili.target_models import BiliPushTargets

_LOGGER = logging.getLogger(__name__)


def _interrupted_result(
    progress: DeliveryProgress, error_code: str, attempt: int
) -> SendResult:
    return SendResult(
        delivered=False,
        error_code=error_code,
        failure_kind=(
            DeliveryFailureKind.RETRYABLE
            if progress.safe_to_retry
            else DeliveryFailureKind.UNCERTAIN
        ),
        failure_phase=progress.phase,
        attempt_count=attempt,
    )


@dataclass(frozen=True, slots=True)
class MediaCleanupResult:
    deleted_files: int = 0
    deleted_bytes: int = 0
    retained_entries: int = 0
    errors: int = 0
    reason: str | None = None


class DynamicDeliveryLedger(Protocol):
    path: Path

    def queue_entry(self, dynamic_id: str) -> dict[str, Any]: ...
    def queue_wait_account(self, dynamic_id: str, target: ConversationRef) -> None: ...

    def queue_claim(
        self, dynamic_id: str, targets: tuple[ConversationRef, ...]
    ) -> set[ConversationRef]: ...
    def queue_wake(
        self, dynamic_id: str, targets: tuple[ConversationRef, ...]
    ) -> None: ...
    def queue_settle(
        self, dynamic_id: str, target: ConversationRef, *, final: bool = False
    ) -> bool: ...
    def queue_ready(self) -> list[dict[str, Any]]: ...

    def begin_media_preparation(
        self, dynamic_id: str, fingerprint: str
    ) -> tuple[int, float]: ...
    def finish_media_preparation(
        self, dynamic_id: str, status: str, diagnostics: dict[str, object]
    ) -> None: ...
    def load_media_source(self, dynamic_id: str, source_key: str) -> bytes | None: ...
    def save_media_source(
        self, dynamic_id: str, source_key: str, content: bytes
    ) -> None: ...

    def acquire_execution(self, key: str, owner: str) -> bool: ...
    def renew_execution(self, key: str, owner: str) -> bool: ...
    def release_execution(self, key: str, owner: str) -> None: ...
    def stage_state(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> str: ...
    def stage_result(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> SendResult | None: ...
    def predecessors_done(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> bool: ...
    def start_stage(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> float: ...
    def expire_stage(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> None: ...
    def block_following(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> None: ...
    def defer_stage(
        self, dynamic_id: str, target: ConversationRef, stage: str, result: SendResult
    ) -> None: ...
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
    def skip_stage(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> None: ...
    def recover(self) -> None: ...
    def cleanup_media(self) -> MediaCleanupResult: ...
    def claim_notification(self, dynamic_id: str) -> bool: ...
    def claim_recovery_report(
        self, dynamic_id: str, counts: dict[str, int]
    ) -> bool: ...
    def unattempted(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> bool: ...
    def freeze_media(
        self, dynamic_id: str, message: OutboundMessage | None
    ) -> OutboundMessage | None: ...
    def load_media(self, dynamic_id: str) -> tuple[bool, OutboundMessage | None]: ...
    def freeze_unit(
        self,
        dynamic_id: str,
        target: ConversationRef,
        stage: str,
        message: OutboundMessage,
    ) -> OutboundMessage: ...
    def load_text(self, dynamic_id: str) -> tuple[bool, OutboundMessage | None]: ...
    def freeze_text(
        self, dynamic_id: str, message: OutboundMessage | None
    ) -> OutboundMessage | None: ...
    def image_units(
        self, dynamic_id: str, target: ConversationRef, count: int
    ) -> bool: ...
    def fail_media(
        self, dynamic_id: str, target: ConversationRef, result: SendResult
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
    on_receipt: Callable[[], None] | None = None

    def capabilities_for(self, conversation: ConversationRef) -> DeliveryCapabilities:
        return self.messenger.capabilities_for(conversation)

    def _finish_interruption(
        self, conversation: ConversationRef, progress: DeliveryProgress, attempt: int
    ) -> None:
        result = _interrupted_result(progress, "interrupted_send", attempt)
        self.ledger.finish(
            self.dynamic_id,
            conversation,
            self.stage,
            result,
        )
        _LOGGER.warning(
            "Bilibili unit interrupted: dynamic=%s unit=%s target=%s attempt=%d "
            "phase=%s kind=%s",
            self.dynamic_id,
            self.stage,
            reference_digest(conversation.id),
            attempt,
            progress.phase or "platform_not_provided",
            result.failure_kind,
        )
        if not progress.safe_to_retry:
            self.ledger.block_following(self.dynamic_id, conversation, self.stage)

    async def send(
        self, conversation: ConversationRef, message: OutboundMessage
    ) -> SendResult:
        try:
            message = self.ledger.freeze_unit(
                self.dynamic_id, conversation, self.stage, message
            )
        except (OSError, ValueError):
            result = SendResult(
                delivered=False,
                error_code="frozen_media_unavailable",
                failure_kind=DeliveryFailureKind.PERMANENT,
            )
            if self.ledger.claim(self.dynamic_id, conversation, self.stage):
                self.ledger.finish(self.dynamic_id, conversation, self.stage, result)
            return result
        if not self.ledger.claim(self.dynamic_id, conversation, self.stage):
            _LOGGER.info(
                "Bilibili unit skipped: dynamic=%s unit=%s round=%d "
                "target=%s reason=ledger_not_claimed",
                self.dynamic_id,
                self.stage,
                delivery_round.get(),
                reference_digest(conversation.id),
            )
            if recorded := self.ledger.stage_result(
                self.dynamic_id, conversation, self.stage
            ):
                return recorded
            return SendResult(
                delivered=False,
                error_code="ledger:not-claimed",
                attempted=False,
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
        progress = delivery_progress.get() or DeliveryProgress()
        progress_token = delivery_progress.set(progress)
        try:
            result = await self.messenger.send(conversation, message)
        except asyncio.CancelledError:
            progress.close()
            self._finish_interruption(conversation, progress, attempt)
            raise
        except Exception as error:  # noqa: BLE001 - a raised transport result is ambiguous
            result = _interrupted_result(progress, type(error).__name__, attempt)
        finally:
            delivery_progress.reset(progress_token)
            delivery_unit.reset(token)
        result = replace(
            result,
            attempt_count=self.ledger.attempts(
                self.dynamic_id, conversation, self.stage
            ),
        )
        self.ledger.finish(self.dynamic_id, conversation, self.stage, result)
        if self.on_receipt is not None:
            self.on_receipt()
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
