import asyncio

from pytest import MonkeyPatch
from typing_extensions import Self

from ironsbot.utils.ai_api_diagnostics import (
    AiApiSettings,
    check_ai_api,
)

HTTP_OK = 200


def test_ai_api_fails_without_key() -> None:
    result = asyncio.run(check_ai_api(AiApiSettings(api_key="")))

    assert not result.ok
    assert result.error == "未配置 AI_KEY"


def test_ai_api_success(monkeypatch: MonkeyPatch) -> None:
    class FakeResponse:
        status_code = HTTP_OK

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
        "ironsbot.utils.ai_api_diagnostics.httpx.AsyncClient",
        FakeAsyncClient,
    )

    result = asyncio.run(check_ai_api(AiApiSettings(api_key="test-key")))

    assert result.ok
    assert result.status_code == HTTP_OK
    assert result.reply == "OK"
