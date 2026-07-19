# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ironsbot.services.ai.history import HistoryMessage
    from ironsbot.services.ai.responses import AiResponseResult


class AiRequestTimeoutError(TimeoutError):
    pass


class AiCompletionClient(Protocol):
    async def complete(
        self,
        messages: list[HistoryMessage],
    ) -> AiResponseResult: ...
