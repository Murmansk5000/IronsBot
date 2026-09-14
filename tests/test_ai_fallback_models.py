import asyncio

from pytest import MonkeyPatch

from ironsbot.app.ai_health import check_configured_ai_api
from ironsbot.integrations.http.ai import (
    AiApiSettings,
    AiApiTestResult,
    HttpAiCompletionClient,
)
from tests.helpers.ai import ai_config

_SERVER_ERROR_STATUS = 500


class _Response:
    def __init__(self, status_code: int, data: object) -> None:
        self.status_code = status_code
        self._data = data
        self.text = str(data)

    def json(self) -> object:
        return self._data


class _Client:
    def __init__(self) -> None:
        self.models: list[str] = []

    async def post(
        self,
        *_: object,
        json: dict[str, object],
        **__: object,
    ) -> _Response:
        model = str(json["model"])
        self.models.append(model)
        if model == "primary":
            return _Response(400, {"error": {"message": "bad model"}})
        return _Response(200, {"choices": [{"message": {"content": "OK"}}]})


def test_ai_config_deduplicates_models_in_priority_order() -> None:
    config = ai_config(models=(" primary ", "backup", "primary", "backup"))

    assert config.endpoints[0].models == ["primary", "backup"]


def test_completion_tries_fallback_after_api_error() -> None:
    config = ai_config(models=("primary", "backup"))
    client = _Client()

    result = asyncio.run(HttpAiCompletionClient(client, config).complete([]))

    assert result.ok
    assert result.reply == "OK"
    assert client.models == ["primary", "backup"]


def test_startup_check_records_first_healthy_model(monkeypatch: MonkeyPatch) -> None:
    class Notice:
        def __init__(self) -> None:
            self.parts: list[tuple[str, str, str]] = []

        def add(
            self,
            subscription_key: str,
            action_name: str,
            message: str | None,
        ) -> None:
            assert message is not None
            self.parts.append((subscription_key, action_name, message))

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
    notice = Notice()
    config = ai_config(models=("primary", "backup"), api_key="secret")

    asyncio.run(
        check_configured_ai_api(config, startup_notice=notice)
    )

    assert calls == ["primary", "backup"]
    assert "可用：test/backup（HTTP 200，12 ms）" in notice.parts[0][2]


def test_completion_returns_last_api_error_when_all_models_fail() -> None:
    class FailingClient:
        async def post(self, *_: object, **__: object) -> _Response:
            return _Response(500, {"error": {"message": "nope"}})

    result = asyncio.run(
        HttpAiCompletionClient(
            FailingClient(),
            ai_config(models=("primary", "backup")),
        ).complete([])
    )

    assert result.status_code == _SERVER_ERROR_STATUS
    assert result.endpoint == "test"
    assert result.model == "primary"
    assert result.error_kind == "http"
    assert result.error_detail == "nope"
