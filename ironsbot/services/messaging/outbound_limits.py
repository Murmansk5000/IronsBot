# SPDX-License-Identifier: MIT
"""Window, queue and permit policy over normalized group and actor facts."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from contextlib import suppress
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Literal

from ironsbot.core.outbound import DeliveryFailureKind, SendResult
from ironsbot.core.platform import ConversationRef, Platform, reference_digest

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.config.models.messaging import (
        OutboundRateLimitConfig,
        OutboundRateLimitWindowConfig,
    )
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.platform import ActorRef
    from ironsbot.core.tasks import TaskSpawner

ADMIN_NOTICE_FEATURE = "admin_notice"
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OutboundPermit:
    token: int
    group_id: int
    reserved_at: float
    append_cooldown_notice: bool = False
    source: str = "reply"


@dataclass(frozen=True, slots=True)
class OutboundRateLimitDecision:
    allowed: bool
    permit: OutboundPermit | None = None
    retry_after_seconds: float = 0.0
    reason: Literal["rate_limit", "queue_cleared"] | None = None


@dataclass(slots=True)
class _OutboundEvent:
    token: int
    created_at: float
    settled: bool = False


@dataclass(slots=True)
class OutboundSendAttempt:
    cooldown_notice: str | None = None
    started: bool = False
    interrupted: bool = False

    def start(self) -> None:
        self.started = True


@dataclass(slots=True)
class MultiWindowGroupRateLimiter:
    _events: dict[int, deque[_OutboundEvent]] = field(
        default_factory=lambda: defaultdict(deque)
    )
    _next_token: int = 1

    def acquire(
        self,
        group_id: int,
        windows: list[OutboundRateLimitWindowConfig],
        *,
        source: str,
        now: float | None = None,
    ) -> OutboundRateLimitDecision:
        current_time = time.monotonic() if now is None else now
        events = self._events[group_id]
        self._trim(events, current_time=current_time, windows=windows)

        retry_after = self._retry_after(
            events,
            current_time=current_time,
            windows=windows,
        )
        if retry_after > 0:
            return OutboundRateLimitDecision(
                allowed=False,
                retry_after_seconds=retry_after,
                reason="rate_limit",
            )

        token = self._next_token
        self._next_token += 1
        events.append(_OutboundEvent(token=token, created_at=current_time))
        append_notice = any(
            self._count_in_window(
                events,
                current_time=current_time,
                window_seconds=window.window_seconds,
            )
            == window.max_messages
            for window in windows
        )
        return OutboundRateLimitDecision(
            allowed=True,
            permit=OutboundPermit(
                token=token,
                group_id=group_id,
                reserved_at=current_time,
                append_cooldown_notice=append_notice,
                source=source,
            ),
        )

    def rollback(self, permit: OutboundPermit) -> bool:
        events = self._events.get(permit.group_id)
        if events is None:
            return False
        for event in events:
            if event.token != permit.token:
                continue
            events.remove(event)
            if not events:
                self._events.pop(permit.group_id, None)
            return True
        return False

    def clear(self) -> None:
        self._events.clear()

    def claim_settlement(self, permit: OutboundPermit) -> bool:
        for event in self._events.get(permit.group_id, ()):
            if event.token == permit.token and not event.settled:
                event.settled = True
                return True
        return False

    @staticmethod
    def _count_in_window(
        events: deque[_OutboundEvent],
        *,
        current_time: float,
        window_seconds: float,
    ) -> int:
        cutoff = current_time - window_seconds
        return sum(event.created_at > cutoff for event in events)

    @classmethod
    def _retry_after(
        cls,
        events: deque[_OutboundEvent],
        *,
        current_time: float,
        windows: list[OutboundRateLimitWindowConfig],
    ) -> float:
        retry_after = 0.0
        for window in windows:
            cutoff = current_time - window.window_seconds
            active = [event for event in events if event.created_at > cutoff]
            if len(active) < window.max_messages:
                continue
            release_event = active[len(active) - window.max_messages]
            retry_after = max(
                retry_after,
                release_event.created_at + window.window_seconds - current_time,
            )
        return max(0.0, retry_after)

    @staticmethod
    def _trim(
        events: deque[_OutboundEvent],
        *,
        current_time: float,
        windows: list[OutboundRateLimitWindowConfig],
    ) -> None:
        max_window_seconds = max(window.window_seconds for window in windows)
        cutoff = current_time - max_window_seconds
        while events and events[0].created_at <= cutoff:
            events.popleft()


@dataclass(slots=True)
class _QueuedOutbound:
    source: str
    priority: Literal["superuser_reply", "push"]
    future: asyncio.Future[OutboundRateLimitDecision]


@dataclass(slots=True)
class _GroupPushQueue:
    superuser_waiters: deque[_QueuedOutbound] = field(default_factory=deque)
    push_waiters: deque[_QueuedOutbound] = field(default_factory=deque)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    worker: asyncio.Task[None] | None = None

    def has_waiters(self) -> bool:
        return bool(self.superuser_waiters or self.push_waiters)

    def next_waiter(self) -> _QueuedOutbound | None:
        for waiters in (self.superuser_waiters, self.push_waiters):
            while waiters:
                waiter = waiters[0]
                if waiter.future.cancelled():
                    waiters.popleft()
                    continue
                return waiter
        return None

    def pop_waiter(self, waiter: _QueuedOutbound) -> None:
        waiters = (
            self.superuser_waiters
            if waiter.priority == "superuser_reply"
            else self.push_waiters
        )
        if waiters and waiters[0] is waiter:
            waiters.popleft()


class GroupOutboundRateLimitService:
    def __init__(
        self,
        config: OutboundRateLimitConfig,
        features: FeatureService,
        spawn: TaskSpawner,
    ) -> None:
        self.config = config
        self.features = features
        self._spawn = spawn
        self._limiter = MultiWindowGroupRateLimiter()
        self._push_queues: dict[int, _GroupPushQueue] = {}

    def acquire_reply(
        self,
        group_id: int | None,
        *,
        now: float | None = None,
    ) -> OutboundRateLimitDecision:
        if group_id is None or not self._is_limited_group(group_id):
            return OutboundRateLimitDecision(allowed=True)
        config = self.config
        return self._limiter.acquire(
            group_id,
            config.windows,
            source="reply",
            now=now,
        )

    async def acquire_send(
        self, group_id: int | None, *, actor: ActorRef | None = None
    ) -> OutboundRateLimitDecision:
        if actor is not None and self.features.is_actor_superuser(actor):
            return await self.acquire_superuser_reply(group_id)
        return self.acquire_reply(group_id)

    async def execute_send(
        self,
        group_id: int | None,
        send: Callable[[OutboundSendAttempt], Awaitable[SendResult]],
        *,
        actor: ActorRef | None = None,
        proactive: bool = False,
    ) -> SendResult:
        decision = (
            await self.acquire_push(group_id, source="platform outbound")
            if proactive
            else await self.acquire_send(group_id, actor=actor)
        )
        if not decision.allowed:
            return SendResult(
                delivered=False,
                attempted=False,
                error_code=decision.reason or "rate_limit",
                failure_kind=DeliveryFailureKind.RETRYABLE,
            )
        attempt = OutboundSendAttempt(
            cooldown_notice=self.config.cooldown_message
            if decision.permit is not None and decision.permit.append_cooldown_notice
            else None,
        )
        try:
            result = await send(attempt)
        except BaseException:
            if not attempt.started:
                self.rollback(decision.permit)
            raise
        self.settle_send(decision.permit, result, interrupted=attempt.interrupted)
        return result

    def settle_send(
        self,
        permit: OutboundPermit | None,
        result: SendResult,
        *,
        interrupted: bool = False,
    ) -> None:
        if permit is None or not self._limiter.claim_settlement(permit):
            return
        if not result.delivered and (
            not result.attempted
            or result.failure_kind
            in {
                DeliveryFailureKind.PERMANENT,
                DeliveryFailureKind.RETRYABLE,
                DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
            }
        ):
            self.rollback(permit)
        if result.attempted and (
            interrupted
            or result.failure_kind is DeliveryFailureKind.TRANSPORT_UNAVAILABLE
        ):
            self.discard_pending_pushes(permit.group_id)

    async def acquire_push(
        self,
        group_id: int | None,
        *,
        source: str,
    ) -> OutboundRateLimitDecision:
        return await self._acquire_queued_outbound(
            group_id,
            source=source,
            priority="push",
        )

    async def acquire_superuser_reply(
        self,
        group_id: int | None,
    ) -> OutboundRateLimitDecision:
        return await self._acquire_queued_outbound(
            group_id,
            source="superuser reply",
            priority="superuser_reply",
        )

    async def _acquire_queued_outbound(
        self,
        group_id: int | None,
        *,
        source: str,
        priority: Literal["superuser_reply", "push"],
    ) -> OutboundRateLimitDecision:
        if group_id is None or not self._is_limited_group(group_id):
            return OutboundRateLimitDecision(allowed=True)

        config = self.config
        queue = self._push_queues.get(group_id)
        if queue is None or not queue.has_waiters():
            immediate = self._limiter.acquire(
                group_id,
                config.windows,
                source=source,
            )
            if immediate.allowed:
                return immediate
        else:
            immediate = OutboundRateLimitDecision(
                allowed=False,
                reason="rate_limit",
            )

        queue = self._push_queues.setdefault(group_id, _GroupPushQueue())
        loop = asyncio.get_running_loop()
        waiter = _QueuedOutbound(
            source=source,
            priority=priority,
            future=loop.create_future(),
        )
        if priority == "superuser_reply":
            queue.superuser_waiters.append(waiter)
        else:
            queue.push_waiters.append(waiter)
        if queue.worker is None or queue.worker.done():
            self._start_queue_worker(group_id, queue)
        queue.changed.set()

        try:
            return await asyncio.shield(waiter.future)
        except asyncio.CancelledError:
            if waiter.future.done() and not waiter.future.cancelled():
                self.rollback(waiter.future.result().permit)
            else:
                waiter.future.cancel()
            queue.changed.set()
            raise

    def discard_pending_pushes(self, group_id: int) -> None:
        """Drop waiting proactive pushes after a real group send failure.

        Superuser-triggered replies use a separate priority lane and remain
        queued so a transient transport failure cannot silently lose them.
        """

        queue = self._push_queues.get(group_id)
        if queue is None:
            return
        while queue.push_waiters:
            waiter = queue.push_waiters.popleft()
            if not waiter.future.done():
                waiter.future.set_result(
                    OutboundRateLimitDecision(
                        allowed=False,
                        reason="queue_cleared",
                    )
                )
        queue.changed.set()

    def rollback(self, permit: OutboundPermit | None) -> None:
        if permit is None or not self._limiter.rollback(permit):
            return
        queue = self._push_queues.get(permit.group_id)
        if queue is not None:
            queue.changed.set()

    def reset(self) -> None:
        self._limiter.clear()
        for queue in self._push_queues.values():
            if queue.worker is not None:
                queue.worker.cancel()
            for waiter in (*queue.superuser_waiters, *queue.push_waiters):
                if not waiter.future.done():
                    waiter.future.cancel()
            queue.superuser_waiters.clear()
            queue.push_waiters.clear()
        self._push_queues.clear()

    async def _run_push_queue(
        self,
        group_id: int,
        queue: _GroupPushQueue,
    ) -> None:
        try:
            while (waiter := queue.next_waiter()) is not None:
                now = time.monotonic()
                if not self._is_limited_group(group_id):
                    queue.pop_waiter(waiter)
                    waiter.future.set_result(OutboundRateLimitDecision(allowed=True))
                    continue

                config = self.config
                decision = self._limiter.acquire(
                    group_id,
                    config.windows,
                    source=waiter.source,
                    now=now,
                )
                if decision.allowed:
                    queue.pop_waiter(waiter)
                    waiter.future.set_result(decision)
                    continue

                delay = max(0.001, decision.retry_after_seconds)
                queue.changed.clear()
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(queue.changed.wait(), timeout=delay)
        except Exception as error:  # noqa: BLE001 - background workers must release waiters
            logger.error(  # noqa: TRY400 - do not expose message or credential details
                "outbound push queue worker failed: conversation_ref=%s error_type=%s",
                reference_digest(str(group_id)),
                type(error).__name__,
            )
            self.discard_pending_pushes(group_id)

    def _start_queue_worker(self, group_id: int, queue: _GroupPushQueue) -> None:
        queue.worker = self._spawn(
            self._run_push_queue(group_id, queue),
            name=f"ironsbot-push-rate-limit-{reference_digest(str(group_id))}",
        )
        queue.worker.add_done_callback(partial(self._worker_finished, group_id, queue))

    def _worker_finished(
        self, group_id: int, queue: _GroupPushQueue, task: asyncio.Task[None]
    ) -> None:
        if self._push_queues.get(group_id) is not queue or queue.worker is not task:
            return
        queue.worker = None
        if task.cancelled():
            for waiter in (*queue.superuser_waiters, *queue.push_waiters):
                waiter.future.cancel()
            queue.superuser_waiters.clear()
            queue.push_waiters.clear()
        if not queue.has_waiters():
            self._push_queues.pop(group_id, None)
        else:
            self._start_queue_worker(group_id, queue)

    def _is_limited_group(self, group_id: int) -> bool:
        return self.config.enabled and not self.features.conversation_has_feature(
            ConversationRef(Platform.ONEBOT, "group", str(group_id)),
            ADMIN_NOTICE_FEATURE,
        )
