from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.config.models.ai import AiConfig
    from ironsbot.services.ai.history import HistoryMessage
    from ironsbot.services.ai.responses import AiResponseResult

    CompletionRequester = Callable[
        [AiConfig, list[HistoryMessage]],
        Awaitable[AiResponseResult],
    ]


@dataclass(slots=True)
class FakeAiCompletionClient:
    config: AiConfig
    request: CompletionRequester

    async def complete(
        self,
        messages: list[HistoryMessage],
    ) -> AiResponseResult:
        return await self.request(self.config, messages)
