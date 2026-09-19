from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.config.models.ai import AiConfig, AiProviderConfig

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

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


def configured_ai_config(
    *,
    api_key: str = "test-key",
    provider: str = "test",
    base_url: str = "https://example.test/v1",
    models: tuple[str, ...] = ("test-model",),
    thinking: bool = False,
    **kwargs: Any,
) -> AiConfig:
    return AiConfig(
        provider_order=[provider],
        providers={
            provider: AiProviderConfig(
                api_key=api_key,
                base_url=base_url,
                models=list(models),
                thinking=thinking,
            )
        },
        **kwargs,
    )
