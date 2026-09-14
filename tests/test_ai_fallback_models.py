import asyncio
import json

import httpx
from pytest import MonkeyPatch

from ironsbot.app.ai_health import check_configured_ai_api
from ironsbot.integrations.http.ai import (
    AiApiSettings,
    AiApiTestResult,
    HttpAiCompletionClient,
)
from ironsbot.services.operations.startup import StartupNoticeService
from tests.helpers.ai import ai_config
from tests.helpers.runtime import build_test_runtime

_SERVER_ERROR_STATUS = 500


def test_ai_config_deduplicates_models_in_priority_order() -> None:
    config = ai_config(models=(" primary ", "backup", "primary", "backup"))

    assert config.endpoints[0].models == ["primary", "backup"]


def test_completion_tries_fallback_after_api_error() -> None:
    config = ai_config(models=("primary", "backup"))
    models: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        models.append(model)
        if model == "primary":
            return httpx.Response(400, json={"error": {"message": "bad model"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await HttpAiCompletionClient(client, config).complete([])

    result = asyncio.run(run())

    assert result.ok
    assert result.reply == "OK"
    assert models == ["primary", "backup"]


def test_startup_check_records_first_healthy_model(monkeypatch: MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_check(settings: AiApiSettings) -> AiApiTestResult:
        calls.append(settings.model)
        return AiApiTestResult(
            ok=settings.model == "backup",
            elapsed_ms=12,
            status_code=200,
            error="bad model",
        )

    monkeypatch.setattr(
        "ironsbot.app.ai_health.check_ai_api",
        fake_check,
    )
    notice = StartupNoticeService(build_test_runtime().admin_notices)
    config = ai_config(models=("primary", "backup"), api_key="secret")

    asyncio.run(check_configured_ai_api(config, startup_notice=notice))

    assert calls == ["primary", "backup"]
    assert "可用：test/backup（HTTP 200，12 ms）" in notice.parts[0].message


def test_completion_returns_last_api_error_when_all_models_fail() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "nope"}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await HttpAiCompletionClient(
                client,
                ai_config(models=("primary", "backup")),
            ).complete([])

    result = asyncio.run(run())

    assert result.status_code == _SERVER_ERROR_STATUS
    assert result.endpoint == "test"
    assert result.model == "primary"
    assert result.error_kind == "http"
    assert result.error_detail == "nope"
