from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.config.models.ai import AiConfig, AiEndpointConfig

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.ai.history import HistoryMessage
    from ironsbot.services.ai.responses import AiResponseResult

    CompletionRequester = Callable[
        [AiConfig, list[HistoryMessage]],
        Awaitable[AiResponseResult],
    ]


def ai_config(
    *,
    models: tuple[str, ...] = ("test-model",),
    api_key: str = "test-key",
    **kwargs: object,
) -> AiConfig:
    """Build the current endpoint-based AI configuration for tests."""

    return AiConfig.model_validate(
        {
            "endpoints": [
                AiEndpointConfig(
                    name="test",
                    base_url="https://example.test/v1",
                    models=list(models),
                    api_key=api_key,
                )
            ],
            **kwargs,
        }
    )


@dataclass(slots=True)
class FakeAiCompletionClient:
    config: AiConfig
    request: CompletionRequester

    async def complete(
        self,
        messages: list[HistoryMessage],
    ) -> AiResponseResult:
        return await self.request(self.config, messages)
