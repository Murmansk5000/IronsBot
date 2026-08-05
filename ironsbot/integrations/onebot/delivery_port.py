# SPDX-License-Identifier: MIT
"""OneBot-only delivery contracts shared by runtime adapters and plugins."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol

from ironsbot.integrations.onebot.targets import (
    OneBotMessageTarget,
    OneBotTargetSendSummary,
)

OneBotMessageLimiter = Callable[[Any, OneBotMessageTarget], Any]


class OneBotMessageDelivery(Protocol):
    """Numeric OneBot delivery boundary used only by OneBot runtime code."""

    async def send_targets(  # noqa: PLR0913
        self,
        targets: Iterable[OneBotMessageTarget],
        message: Any,
        *,
        bot: Any | None = None,
        action_name: str = "message action",
        interval_seconds: float = 1.5,
        message_limiter: OneBotMessageLimiter | None = None,
        subscription_key: str | None = None,
    ) -> OneBotTargetSendSummary: ...

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
        message_limiter: OneBotMessageLimiter | None = None,
        subscription_key: str | None = None,
    ) -> OneBotTargetSendSummary: ...

    def default_bot(self) -> Any | None: ...

    def bot_for_target(self, target: OneBotMessageTarget) -> Any | None: ...
