# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING

from nonebot.log import logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable

    from ironsbot.core.messaging import (
        DeliveryReceipt,
        MessageTarget,
        TargetSendSummary,
    )


def push_target_sort_key(
    target: MessageTarget,
    index: int,
    *,
    group_alias_order: tuple[int, ...],
    user_alias_order: tuple[int, ...],
) -> tuple[int, int, int, int]:
    target_type_order = 0 if target.target_type == "group" else 1
    aliases = group_alias_order if target_type_order == 0 else user_alias_order
    alias_order = {target_id: position for position, target_id in enumerate(aliases)}
    position = alias_order.get(target.target_id)
    return (
        target_type_order,
        0 if position is not None else 1,
        position if position is not None else target.target_id,
        index,
    )


def ordered_push_targets(
    targets: Iterable[MessageTarget],
    *,
    group_alias_order: tuple[int, ...],
    user_alias_order: tuple[int, ...],
) -> list[MessageTarget]:
    return [
        target
        for index, target in sorted(
            enumerate(targets),
            key=lambda item: push_target_sort_key(
                item[1],
                item[0],
                group_alias_order=group_alias_order,
                user_alias_order=user_alias_order,
            ),
        )
    ]


@dataclass(slots=True)
class PushBatchCoordinator:
    """Prevent concurrent background batches from overloading one QQ client."""

    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    _locks_guard: asyncio.Lock = field(default_factory=asyncio.Lock)

    @asynccontextmanager
    async def acquire(self, bot_keys: Iterable[str]) -> AsyncIterator[None]:
        keys = sorted(set(bot_keys))
        async with self._locks_guard:
            locks = [self._locks.setdefault(key, asyncio.Lock()) for key in keys]
        for lock in locks:
            await lock.acquire()
        try:
            yield
        finally:
            for lock in reversed(locks):
                lock.release()


@dataclass(frozen=True, slots=True)
class TargetSendResult:
    sent: bool
    receipt: DeliveryReceipt | None = None
    uncertain: bool = False
    transport_unavailable: bool = False


@dataclass(frozen=True, slots=True)
class PushBatchResult:
    summary: TargetSendSummary
    transport_unavailable: bool = False


def delivery_error_text(error: Exception) -> str:
    parts = [type(error).__name__, str(error), repr(error)]
    for attribute in ("retcode", "code", "status", "message", "info", "data"):
        value = getattr(error, attribute, None)
        if value is not None:
            parts.append(str(value))
    return " ".join(parts).casefold()


def is_transport_unavailable_error(error: Exception) -> bool:
    """Return whether QQ's sending transport is clearly unavailable."""
    error_text = delivery_error_text(error)
    return any(
        marker in error_text
        for marker in (
            "1006514",
            "网络连接异常",
            "账号状态为离线",
            "账号已离线",
            "not connected",
            "connection closed",
            "connection reset",
            "websocket is closed",
        )
    )


def is_uncertain_delivery_error(error: Exception) -> bool:
    """Return whether the request may have reached QQ without a response."""
    if is_transport_unavailable_error(error):
        return False
    error_name = type(error).__name__.casefold()
    message = delivery_error_text(error)
    return (
        "timeout" in error_name
        or "network" in error_name
        or "connection" in error_name
        or "timeout" in message
        or "websocket" in message
        or "connection" in message
    )


@dataclass(slots=True)
class OneBotTransportCircuit:
    _open_until_by_bot: dict[str, float] = field(default_factory=dict)

    @staticmethod
    def _bot_key(bot: object) -> str:
        return str(getattr(bot, "self_id", id(bot)))

    def is_open(self, bot: object) -> bool:
        key = self._bot_key(bot)
        open_until = self._open_until_by_bot.get(key, 0.0)
        if open_until <= monotonic():
            self._open_until_by_bot.pop(key, None)
            return False
        return True

    def open(self, bot: object, cooldown_seconds: float, error: Exception) -> None:
        key = self._bot_key(bot)
        self._open_until_by_bot[key] = monotonic() + cooldown_seconds
        logger.error(
            "OneBot push transport circuit opened: bot={} cooldown={}s error={}: {}",
            key,
            cooldown_seconds,
            type(error).__name__,
            error,
        )

    def close(self, bot: object) -> None:
        self._open_until_by_bot.pop(self._bot_key(bot), None)
