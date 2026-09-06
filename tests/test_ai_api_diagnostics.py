import asyncio
import json

import httpx
from pytest import MonkeyPatch
from typing_extensions import Self

from ironsbot.config.models.ai import AiConfig, AiEndpointConfig
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
                    endpoints=[
                        AiEndpointConfig(
                            name="primary",
                            base_url="https://example.test/v1",
                            models=["primary", "backup", "unused"],
                            api_key="test-key",
                        )
                    ]
                ),
            )
            return await completion.complete([{"role": "user", "content": "hi"}])

    result = asyncio.run(run())

    assert requested_models == ["primary", "backup"]
    assert result.ok
    assert result.endpoint == "primary"
    assert result.model == "backup"
    assert result.reply == "备用模型回复"


def test_ai_completion_switches_endpoint_after_auth_failure() -> None:
    requested: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requested.append(
            (
                request.url.host or "",
                str(payload["model"]),
                request.headers["Authorization"],
            )
        )
        if request.url.host == "primary.test":
            return httpx.Response(403, json={"error": {"message": "denied"}})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "备用端点回复"}}]},
        )

    async def run() -> AiResponseResult:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            completion = HttpAiCompletionClient(
                client,
                AiConfig(
                    endpoints=[
                        AiEndpointConfig(
                            name="primary",
                            base_url="https://primary.test/v1",
                            models=["first", "unused"],
                            api_key="primary-key",
                        ),
                        AiEndpointConfig(
                            name="backup",
                            base_url="https://backup.test/v1",
                            models=["fallback"],
                            api_key="backup-key",
                        ),
                    ]
                ),
            )
            return await completion.complete([{"role": "user", "content": "hi"}])

    result = asyncio.run(run())

    assert requested == [
        ("primary.test", "first", "Bearer primary-key"),
        ("backup.test", "fallback", "Bearer backup-key"),
    ]
    assert result.ok
    assert result.endpoint == "backup"
    assert result.model == "fallback"
    assert [attempt.endpoint for attempt in result.attempts] == ["primary"]
