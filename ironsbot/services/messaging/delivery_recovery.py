# SPDX-License-Identifier: MIT
"""Lifecycle-owned recovery of already-created proactive delivery units."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.core.outbound import DeliveryFailureKind, SendResult
from ironsbot.services.messaging.proactive_delivery import ProactiveDeliveryRequest

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.outbound import OutboundMessage
    from ironsbot.core.platform import BotAccountRef
    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.services.messaging.delivery_tasks import (
        DeliveryTaskStore,
        StoredDelivery,
    )
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProactiveRecovery:
    delivery: ProactiveMessageDelivery
    store: DeliveryTaskStore
    spawn: TaskSpawner
    notify: Callable[[str], Awaitable[None]] | None = None
    additional: Callable[[str], Awaitable[None]] | None = None
    validate: Callable[[StoredDelivery], bool] | None = None
    prepare: Callable[[StoredDelivery], Awaitable[OutboundMessage]] | None = None
    finished: Callable[[StoredDelivery, OutboundMessage, SendResult], None] | None = (
        None
    )
    _wake: asyncio.Event = field(default_factory=asyncio.Event)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _task: asyncio.Task[None] | None = None
    _additional_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self.store.recover()
        self.store.set_waker(self._wake.set)
        if self._task is None:
            self._task = self.spawn(self.run(), name="push.recovery")

    async def stop(self) -> None:
        self.store.set_waker(None)
        tasks = tuple(
            task for task in (self._task, self._additional_task) if task is not None
        )
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._task = self._additional_task = None

    async def connected(self, account: BotAccountRef) -> None:
        self.store.wake(account.id, platform=account.platform)
        self._wake.set()

    async def run(self) -> None:
        while True:
            try:
                await self.scan()
            except Exception:
                logger.exception("proactive recovery scan failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=30)
                self._wake.clear()
            except TimeoutError:
                pass

    def _allowed(self, task: StoredDelivery) -> bool:
        from ironsbot.services.messaging.proactive_prepare import allowed_request

        return (self.validate is None or self.validate(task)) and allowed_request(
            self.delivery,
            ProactiveDeliveryRequest(
                task.conversation, task.message, task.id, task.intent
            ),
            task.subscription,
        )

    async def scan(self) -> None:
        async with self._lock:
            tasks = self.store.due()
            # Targets progress independently; units within one target stay ordered.
            groups: dict[str, list[StoredDelivery]] = {}
            for task in tasks:
                groups.setdefault(str(task.conversation), []).append(task)
            limit = self.delivery.policy.max_parallel_targets
            semaphore = asyncio.Semaphore(limit) if limit > 0 else None

            async def target_units(units: list[StoredDelivery]) -> None:
                if semaphore is None:
                    await self._send_units(units)
                else:
                    async with semaphore:
                        await self._send_units(units)

            results = await asyncio.gather(
                *(target_units(units) for units in groups.values()),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.warning(
                        "proactive target recovery interrupted: error_type=%s",
                        type(result).__name__,
                    )
            if self.additional is not None and (
                self._additional_task is None or self._additional_task.done()
            ):
                self._additional_task = self.spawn(
                    self._recover_additional(),
                    name="push.bilibili-recovery",
                )
            counts = self.store.changes()
            relevant = {
                key: count
                for key, count in counts.items()
                if key not in {"pending", "sending", "superseded"}
            }
            if relevant and self.notify is not None:
                labels = {
                    "success": "已送达",
                    "retry": "正在重试",
                    "waiting": "等待恢复",
                    "permanent": "失败或已停止",
                    "uncertain": "结果不确定，待确认",
                    "expired": "已过期",
                    "blocked": "等待前序处理，已停止续传",
                }
                try:
                    await self.notify(
                        "主动推送恢复汇总\n"
                        + "\n".join(
                            f"{labels.get(key, key)}：{count}"
                            for key, count in relevant.items()
                        )
                    )
                except Exception:
                    logger.exception("proactive recovery summary failed")

    async def _recover_additional(self) -> None:
        try:
            if self.additional is not None:
                await self.additional("scan")
        except Exception:
            logger.exception("Bilibili background recovery failed")

    async def _send_units(self, tasks: list[StoredDelivery]) -> None:
        for task in tasks:
            if not self.store.account_ready(task.conversation):
                continue
            if not self._allowed(task):
                self.store.skip(task.id, "current_policy_rejected")
                continue
            message = (
                await self.prepare(task) if self.prepare is not None else task.message
            )
            summary = await self.delivery.send_many(
                (
                    ProactiveDeliveryRequest(
                        task.conversation, message, task.id, task.intent
                    ),
                ),
                action_name=task.action,
                subscription_key=task.subscription,
                max_attempts=1,
            )
            result = dict(summary.results).get(task.conversation)
            if self.finished is not None:
                self.finished(
                    task,
                    message,
                    result
                    or SendResult(
                        delivered=False,
                        error_code="policy_skipped",
                        attempted=False,
                        failure_kind=DeliveryFailureKind.PERMANENT,
                    ),
                )
            if result is not None and result.delivered:
                self.store.wake(
                    task.conversation.account_id or "",
                    platform=task.conversation.platform,
                )
            elif result is not None and result.failure_kind in {
                DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
                DeliveryFailureKind.RETRYABLE,
            }:
                self.store.account_failed(task.conversation)
