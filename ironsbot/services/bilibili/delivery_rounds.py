# SPDX-License-Identifier: MIT
"""Durable Bilibili retry rounds with per-dynamic failure-sized batches."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.delivery_attempt import delivery_round
from ironsbot.core.outbound import DeliveryFailureKind
from ironsbot.core.platform import reference_digest
from ironsbot.services.messaging.retry_batches import (
    retry_batch_size,
    run_delivery_batches,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.outbound import SendResult
    from ironsbot.core.platform import ConversationRef
    from ironsbot.services.bilibili.delivery_ledger import DynamicDeliveryLedger
    from ironsbot.services.messaging.proactive_delivery import ProactiveDeliveryPolicy

BILI_RETRY_DELAYS = (2.0, 5.0, 10.0)
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DynamicRetryPlan:
    dynamic_id: str
    policy: ProactiveDeliveryPolicy
    ledger: DynamicDeliveryLedger | None = None

    async def run(
        self,
        targets: list[ConversationRef],
        send: Callable[[ConversationRef], Awaitable[None]],
        failures: dict[tuple[ConversationRef, str], SendResult],
        *,
        resume: bool,
    ) -> None:
        pending = targets
        first_round = (
            min(
                self.ledger.completed_round_count(self.dynamic_id),
                len(BILI_RETRY_DELAYS),
            )
            if self.ledger
            else 0
        )
        for round_index in range(first_round, len(BILI_RETRY_DELAYS) + 1):
            if not pending:
                break
            if round_index or resume:
                delay = (
                    self.ledger.retry_delay(self.dynamic_id)
                    if self.ledger
                    else BILI_RETRY_DELAYS[round_index - 1]
                    if round_index
                    else 0.0
                )
                if delay is None and round_index > first_round:
                    logger.info(
                        "Bilibili retries stopped: dynamic=%s "
                        "reason=no_retryable_units",
                        self.dynamic_id,
                    )
                    break
                if delay is not None and delay > 0:
                    logger.info(
                        "Bilibili retry waiting: dynamic=%s next_round=%d "
                        "delay_seconds=%.3f targets=%d",
                        self.dynamic_id,
                        round_index + 1,
                        delay,
                        len(pending),
                    )
                    await asyncio.sleep(delay)
            if self.ledger is not None and not self.ledger.begin_round(self.dynamic_id):
                logger.info(
                    "Bilibili retries stopped: dynamic=%s "
                    "reason=round_budget_exhausted",
                    self.dynamic_id,
                )
                break
            batch_size = retry_batch_size(
                len(pending),
                self.policy.max_parallel_targets,
                self.policy.retry_batch_divisor,
                retry=round_index > 0,
            )
            round_started = time.monotonic()
            positions = {target: index for index, target in enumerate(pending)}
            logger.info(
                "Bilibili round started: dynamic=%s round=%d targets=%d "
                "batch_size=%d batches=%d max_parallel=%d divisor=%d resume=%s",
                self.dynamic_id,
                round_index + 1,
                len(pending),
                batch_size,
                (len(pending) + batch_size - 1) // batch_size,
                self.policy.max_parallel_targets,
                self.policy.retry_batch_divisor,
                resume,
            )

            async def traced_send(
                target: ConversationRef,
                *,
                current_round: int = round_index + 1,
                target_positions: dict[ConversationRef, int] = positions,
                capacity: int = batch_size,
                queued_at: float = round_started,
            ) -> None:
                started = time.monotonic()
                batch = target_positions[target] // capacity + 1
                marker = delivery_round.set(current_round)
                logger.info(
                    "Bilibili target started: dynamic=%s round=%d batch=%d "
                    "platform=%s kind=%s target=%s account=%s queue_ms=%d",
                    self.dynamic_id,
                    current_round,
                    batch,
                    target.platform.value,
                    target.kind,
                    reference_digest(target.id),
                    target.account_id or "auto",
                    int((started - queued_at) * 1000),
                )
                try:
                    await send(target)
                except Exception as error:
                    logger.warning(
                        "Bilibili target aborted: dynamic=%s round=%d "
                        "target=%s exception=%s",
                        self.dynamic_id,
                        current_round,
                        reference_digest(target.id),
                        type(error).__name__,
                    )
                    raise
                finally:
                    logger.info(
                        "Bilibili target finished: dynamic=%s round=%d batch=%d "
                        "target=%s elapsed_ms=%d failed_units=%d",
                        self.dynamic_id,
                        current_round,
                        batch,
                        reference_digest(target.id),
                        int((time.monotonic() - started) * 1000),
                        sum(
                            1
                            for conversation, _stage in failures
                            if conversation == target
                        ),
                    )
                    delivery_round.reset(marker)

            await run_delivery_batches(
                pending,
                traced_send,
                batch_size=batch_size,
            )
            if self.ledger is not None:
                self.ledger.finish_round(self.dynamic_id)
            pending = list(
                dict.fromkeys(
                    target
                    for (target, _stage), result in failures.items()
                    if result.failure_kind is DeliveryFailureKind.RETRYABLE
                )
            )
            logger.info(
                "Bilibili round finished: dynamic=%s round=%d elapsed_ms=%d "
                "retry_targets=%d failed_units=%d uncertain_units=%d",
                self.dynamic_id,
                round_index + 1,
                int((time.monotonic() - round_started) * 1000),
                len(pending),
                len(failures),
                sum(
                    result.failure_kind is DeliveryFailureKind.UNCERTAIN
                    for result in failures.values()
                ),
            )
