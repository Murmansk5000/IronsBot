# SPDX-License-Identifier: MIT
"""Durable delivery values; no transport handles or callbacks are persisted."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

from ironsbot.core.time import TZ_CN, now

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.outbound import OutboundMessage, SendResult
    from ironsbot.core.platform import ConversationRef, Platform


@dataclass(frozen=True, slots=True)
class DeliveryIntent:
    key: str
    expires_at: float
    feature: str = ""
    sequence: str = ""
    position: int = 0
    supersedes: str = ""
    source_id: str = ""
    source_platform: str = ""
    source_account: str | None = None
    skin_choices: tuple[tuple[int, int, str], ...] = ()


def daily_delivery_expiry() -> float:
    current = now().astimezone(TZ_CN)
    return (
        (current + timedelta(days=1))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp()
    )


@dataclass(frozen=True, slots=True)
class StoredDelivery:
    id: str
    conversation: ConversationRef
    message: OutboundMessage
    intent: DeliveryIntent
    action: str
    subscription: str | None
    max_attempts: int
    delays: tuple[float, ...]
    result: SendResult | None = None


class DeliveryTaskStore(Protocol):
    def prepare(self, task: StoredDelivery) -> OutboundMessage: ...
    def claim(self, task_id: str) -> bool: ...
    def finish(self, task_id: str, result: SendResult) -> None: ...
    def result(self, task_id: str) -> SendResult: ...
    def due(self) -> list[StoredDelivery]: ...
    def recover(self) -> None: ...
    def skip(self, task_id: str, reason: str) -> None: ...
    def changes(self) -> dict[str, int]: ...
    def wake(self, account: str = "", *, platform: Platform | None = None) -> None: ...
    def account_ready(self, target: ConversationRef) -> bool: ...
    def account_failed(self, target: ConversationRef) -> None: ...
    def set_waker(self, wake: Callable[[], None] | None) -> None: ...
