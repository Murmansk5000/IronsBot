# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.core.messaging import MessageTarget

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.core.messaging import TargetSendSummary

MessageLimiter = Callable[[Any, MessageTarget], Any]


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
    ) -> TargetSendSummary: ...

    def default_bot(self) -> Any | None: ...

    def bot_for_target(self, target: MessageTarget) -> Any | None: ...
