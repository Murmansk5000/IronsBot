# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.core.messaging import DeliveryReceipt, MessageTarget

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.core.messaging import TargetSendSummary

MessageLimiter = Callable[[Any, MessageTarget], Any]
DeliveryReceiptHandler = Callable[[DeliveryReceipt], Awaitable[None] | None]


class MessageDelivery(Protocol):
    async def send_targets(  # noqa: PLR0913
        self,
        targets: Iterable[MessageTarget],
        message: Any,
        *,
        bot: Any | None = None,
        action_name: str = "message action",
        interval_seconds: float = 1.5,
        message_limiter: MessageLimiter | None = None,
        subscription_key: str | None = None,
        retry_failed_targets: bool = True,
    ) -> TargetSendSummary: ...

    async def send_target_messages(  # noqa: PLR0913
        self,
        target_messages: Iterable[tuple[MessageTarget, Any]],
        *,
        bot: Any | None = None,
        action_name: str = "message action",
        message_limiter: MessageLimiter | None = None,
        subscription_key: str | None = None,
        retry_failed_targets: bool = True,
        receipt_handler: DeliveryReceiptHandler | None = None,
        verify_history: bool = False,
    ) -> TargetSendSummary: ...

    async def broadcast(  # noqa: PLR0913
        self,
        message: Any,
        *,
        private_user_ids: Iterable[int] = (),
        group_ids: Iterable[int] = (),
        group_at_user_ids: Iterable[int] = (),
        bot: Any | None = None,
        action_name: str = "message action",
        interval_seconds: float = 1.5,
        message_limiter: MessageLimiter | None = None,
        subscription_key: str | None = None,
        retry_failed_targets: bool = True,
    ) -> TargetSendSummary: ...

    def default_bot(self) -> Any | None: ...

    def bot_for_target(self, target: MessageTarget) -> Any | None: ...
