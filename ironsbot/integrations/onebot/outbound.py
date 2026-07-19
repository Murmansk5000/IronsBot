# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any, Literal

from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.exception import MockApiException
from nonebot.log import logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.config.models.messaging import (
        OutboundRateLimitConfig,
        OutboundRateLimitWindowConfig,
    )
    from ironsbot.core.features import FeatureService
    from ironsbot.core.tasks import TaskSpawner

ADMIN_NOTICE_FEATURE = "admin_notice"
_SUPPORTED_GROUP_SEND_APIS = frozenset(("send_msg", "send_group_msg"))
_SUPPRESSED_RESULT_KEY = "_ironsbot_outbound_suppressed"


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
    reason: Literal["rate_limit", "queue_full", "queue_timeout"] | None = None


@dataclass(frozen=True, slots=True)
class _OutboundEvent:
    token: int
    created_at: float


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
        self._next_token = 1

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
class _PushWaiter:
    source: str
    deadline: float
    future: asyncio.Future[OutboundRateLimitDecision]


@dataclass(slots=True)
class _GroupPushQueue:
    waiters: deque[_PushWaiter] = field(default_factory=deque)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    worker: asyncio.Task[None] | None = None


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
        self._api_permits: dict[int, OutboundPermit] = {}
        self._preacquired_push_permit: ContextVar[
            OutboundPermit | None
        ] = ContextVar(
            "ironsbot_preacquired_push_permit",
            default=None,
        )

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

    async def acquire_push(
        self,
        group_id: int | None,
        *,
        source: str,
    ) -> OutboundRateLimitDecision:
        if group_id is None or not self._is_limited_group(group_id):
            return OutboundRateLimitDecision(allowed=True)

        config = self.config
        queue = self._push_queues.get(group_id)
        if queue is None or not queue.waiters:
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
        if (
            config.push_queue_max_wait_seconds <= 0
            or config.push_queue_max_messages <= 0
        ):
            return OutboundRateLimitDecision(
                allowed=False,
                retry_after_seconds=immediate.retry_after_seconds,
                reason="queue_timeout",
            )

        queue = self._push_queues.setdefault(group_id, _GroupPushQueue())
        if len(queue.waiters) >= config.push_queue_max_messages:
            return OutboundRateLimitDecision(
                allowed=False,
                retry_after_seconds=immediate.retry_after_seconds,
                reason="queue_full",
            )

        loop = asyncio.get_running_loop()
        waiter = _PushWaiter(
            source=source,
            deadline=time.monotonic() + config.push_queue_max_wait_seconds,
            future=loop.create_future(),
        )
        queue.waiters.append(waiter)
        if queue.worker is None or queue.worker.done():
            queue.worker = self._spawn(
                self._run_push_queue(group_id, queue),
                name=f"ironsbot-push-rate-limit-{group_id}",
            )
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

    def rollback(self, permit: OutboundPermit | None) -> None:
        if permit is None or not self._limiter.rollback(permit):
            return
        queue = self._push_queues.get(permit.group_id)
        if queue is not None:
            queue.changed.set()

    def reset(self) -> None:
        self._limiter.clear()
        self._api_permits.clear()
        for queue in self._push_queues.values():
            if queue.worker is not None:
                queue.worker.cancel()
            for waiter in queue.waiters:
                if not waiter.future.done():
                    waiter.future.cancel()
        self._push_queues.clear()

    async def _run_push_queue(
        self,
        group_id: int,
        queue: _GroupPushQueue,
    ) -> None:
        try:
            while queue.waiters:
                waiter = queue.waiters[0]
                if waiter.future.cancelled():
                    queue.waiters.popleft()
                    continue

                now = time.monotonic()
                remaining_wait = waiter.deadline - now
                if remaining_wait <= 0:
                    queue.waiters.popleft()
                    waiter.future.set_result(
                        OutboundRateLimitDecision(
                            allowed=False,
                            reason="queue_timeout",
                        )
                    )
                    continue

                if not self._is_limited_group(group_id):
                    queue.waiters.popleft()
                    waiter.future.set_result(
                        OutboundRateLimitDecision(allowed=True)
                    )
                    continue

                config = self.config
                decision = self._limiter.acquire(
                    group_id,
                    config.windows,
                    source=waiter.source,
                    now=now,
                )
                if decision.allowed:
                    queue.waiters.popleft()
                    waiter.future.set_result(decision)
                    continue

                delay = min(
                    remaining_wait,
                    max(0.001, decision.retry_after_seconds),
                )
                queue.changed.clear()
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(queue.changed.wait(), timeout=delay)
        except Exception:  # noqa: BLE001 - background workers must release waiters
            logger.exception(
                "outbound push queue worker failed: group={}",
                group_id,
            )
            while queue.waiters:
                waiter = queue.waiters.popleft()
                if not waiter.future.done():
                    waiter.future.set_result(
                        OutboundRateLimitDecision(
                            allowed=False,
                            reason="queue_timeout",
                        )
                    )
        finally:
            queue.worker = None
            if not queue.waiters:
                self._push_queues.pop(group_id, None)

    def _is_limited_group(self, group_id: int) -> bool:
        return self.config.enabled and not self.features.group_has_feature(
            group_id,
            ADMIN_NOTICE_FEATURE,
        )


def _extract_group_id(api: str, data: dict[str, Any]) -> int | None:
    if not (
        api == "send_group_msg"
        or (
            api == "send_msg"
            and (
                data.get("message_type") == "group"
                or data.get("group_id") is not None
            )
        )
    ):
        return None
    raw_group_id = data.get("group_id")
    if raw_group_id is None:
        return None
    try:
        group_id = int(raw_group_id)
    except (TypeError, ValueError):
        return None
    return group_id if group_id > 0 else None


def _append_cooldown_notice(data: dict[str, Any], notice: str) -> None:
    message = Message(data.get("message", ""))
    message += MessageSegment.text(f"\n\n{notice}")
    data["message"] = message


def _suppressed_result(
    *,
    group_id: int,
    reason: str,
) -> dict[str, object]:
    return {
        _SUPPRESSED_RESULT_KEY: True,
        "group_id": group_id,
        "reason": reason,
    }


def is_outbound_suppressed_result(result: object) -> bool:
    return (
        isinstance(result, dict)
        and result.get(_SUPPRESSED_RESULT_KEY) is True
    )


@contextmanager
def use_preacquired_push_permit(
    service: GroupOutboundRateLimitService,
    permit: OutboundPermit | None,
) -> Iterator[None]:
    token = service._preacquired_push_permit.set(permit)
    try:
        yield
    finally:
        service._preacquired_push_permit.reset(token)


async def _check_group_send_api(
    service: GroupOutboundRateLimitService,
    _bot: Bot,
    api: str,
    data: dict[str, Any],
) -> None:
    if api not in _SUPPORTED_GROUP_SEND_APIS:
        return
    group_id = _extract_group_id(api, data)
    if group_id is None:
        return

    preacquired = service._preacquired_push_permit.get()
    if preacquired is not None and preacquired.group_id == group_id:
        permit = preacquired
        decision = OutboundRateLimitDecision(allowed=True, permit=permit)
    else:
        decision = service.acquire_reply(group_id)
        permit = decision.permit

    if not decision.allowed:
        logger.info(
            "group message suppressed by outbound rate limit: group={}, api={}",
            group_id,
            api,
        )
        raise MockApiException(
            _suppressed_result(
                group_id=group_id,
                reason=decision.reason or "rate_limit",
            )
        )

    if permit is None:
        return
    service._api_permits[id(data)] = permit
    if permit.append_cooldown_notice:
        notice = service.config.cooldown_message
        _append_cooldown_notice(data, notice)


async def _finalize_group_send_api(
    service: GroupOutboundRateLimitService,
    _bot: Bot,
    exception: Exception | None,
    api: str,
    data: dict[str, Any],
    _result: Any,
) -> None:
    if api not in _SUPPORTED_GROUP_SEND_APIS:
        return
    permit = service._api_permits.pop(id(data), None)
    if exception is not None:
        service.rollback(permit)
def install_outbound_rate_limit_hooks(
    service: GroupOutboundRateLimitService,
) -> None:
    Bot.on_calling_api(partial(_check_group_send_api, service))
    Bot.on_called_api(partial(_finalize_group_send_api, service))
