import asyncio

from pytest import MonkeyPatch

from ironsbot.app.ai_health import check_configured_ai_api
from ironsbot.config.models.ai import AiConfig, AiProviderConfig
from ironsbot.integrations.http.ai import (
    AiApiSettings,
    AiApiTestResult,
    HttpAiCompletionClient,
)
from ironsbot.services.ai.responses import AiResponseResult
from tests.helpers.ai import configured_ai_config


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
            return _Response(429, {"error": {"message": "limited"}})
        return _Response(200, {"choices": [{"message": {"content": "OK"}}]})


def test_ai_config_deduplicates_models_in_priority_order() -> None:
    config = configured_ai_config(
        models=(" primary ", "backup", "primary", "backup"),
    )

    assert config.providers["test"].models == ["primary", "backup"]


def test_completion_tries_fallback_after_api_error() -> None:
    config = configured_ai_config(models=("primary", "backup"))
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
    config = configured_ai_config(api_key="secret", models=("primary", "backup"))

    asyncio.run(check_configured_ai_api(config, startup_notice=notice))

    assert calls == ["primary", "backup"]
    assert notice.parts == [
        (
            "startup_ai_api_check",
            "AI API startup check",
            "AI API 检查通过。\n提供商/模型：test/backup\nHTTP：200\n耗时：12 ms",
        )
    ]


def test_completion_returns_last_api_error_when_all_models_fail() -> None:
    class FailingClient:
        async def post(self, *_: object, **__: object) -> _Response:
            return _Response(500, {"error": {"message": "nope"}})

    result = asyncio.run(
        HttpAiCompletionClient(
            FailingClient(),
            configured_ai_config(models=("primary", "backup")),
        ).complete([])
    )

    assert result == AiResponseResult(
        status_code=500,
        provider="test",
        model="backup",
        error_kind="http",
        error_title="接口返回异常",
        error_detail="nope",
    )


def test_completion_uses_next_provider_after_auth_failure() -> None:
    class ProviderClient:
        def __init__(self) -> None:
            self.urls: list[str] = []

        async def post(self, url: str, *_: object, **__: object) -> _Response:
            self.urls.append(url)
            if "primary.test" in url:
                return _Response(401, {"error": {"message": "bad key"}})
            return _Response(200, {"choices": [{"message": {"content": "OK"}}]})

    config = AiConfig(
        provider_order=["primary", "backup"],
        providers={
            "primary": AiProviderConfig(
                api_key="first",
                base_url="https://primary.test/v1",
                models=["one", "two"],
            ),
            "backup": AiProviderConfig(
                api_key="second",
                base_url="https://backup.test/v1",
                models=["three"],
            ),
        },
    )
    client = ProviderClient()

    result = asyncio.run(HttpAiCompletionClient(client, config).complete([]))

    assert result.ok
    assert result.provider == "backup"
    assert result.model == "three"
    assert client.urls == [
        "https://primary.test/v1/chat/completions",
        "https://backup.test/v1/chat/completions",
    ]
