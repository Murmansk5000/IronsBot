import asyncio
import json

import httpx
from pytest import MonkeyPatch
from typing_extensions import Self

from ironsbot.config.models.ai import AiConfig
from ironsbot.integrations.http.ai import (
    AiApiSettings,
    HttpAiCompletionClient,
    check_ai_api,
)
from ironsbot.services.ai.responses import AiResponseResult

HTTP_OK = 200


def test_ai_api_fails_without_key() -> None:
    result = asyncio.run(check_ai_api(AiApiSettings(api_key="")))

    assert not result.ok
    assert result.error == "未配置 AI_KEY"


def test_ai_api_success(monkeypatch: MonkeyPatch) -> None:
    class FakeResponse:
        status_code = HTTP_OK
        text = ""

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "OK",
                        },
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, *_: object, **__: object) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(
        "ironsbot.integrations.http.ai.httpx.AsyncClient",
        FakeAsyncClient,
    )

    result = asyncio.run(check_ai_api(AiApiSettings(api_key="test-key")))

    assert result.ok
    assert result.status_code == HTTP_OK
    assert result.reply == "OK"


def test_ai_completion_uses_fallback_models_in_order() -> None:
    requested_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        model = str(payload["model"])
        requested_models.append(model)
        if model == "primary":
            return httpx.Response(404, json={"error": {"message": "missing"}})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "备用模型回复"}}]},
        )

    async def run() -> AiResponseResult:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            completion = HttpAiCompletionClient(
                client,
                AiConfig(
                    api_key="test-key",
                    model="primary",
                    fallback_models=["backup", "unused"],
                ),
            )
            return await completion.complete([{"role": "user", "content": "hi"}])

    result = asyncio.run(run())

    assert requested_models == ["primary", "backup"]
    assert result.ok
    assert result.model == "backup"
    assert result.reply == "备用模型回复"
