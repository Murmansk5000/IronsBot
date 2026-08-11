from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from ironsbot.config.models.ai import AiConfig
from ironsbot.integrations.http.ai import AiApiSettings, AiApiTestResult
from ironsbot.plugins.ai import health

if TYPE_CHECKING:
    from pytest import MonkeyPatch

    from ironsbot.services.operations.startup import StartupNoticeService


class _StartupNoticeRecorder:
    def __init__(self) -> None:
        self.parts: list[tuple[str, str, str]] = []

    def add(self, subscription_key: str, action_name: str, message: str) -> None:
        self.parts.append((subscription_key, action_name, message))


def test_configured_ai_key_is_checked_on_startup(
    monkeypatch: MonkeyPatch,
) -> None:
    received: list[AiApiSettings] = []

    async def fake_check(settings: AiApiSettings) -> AiApiTestResult:
        received.append(settings)
        return AiApiTestResult(ok=True, elapsed_ms=42, status_code=200, reply="OK")

    monkeypatch.setattr(health, "check_ai_api", fake_check)
    config = AiConfig(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        timeout=45,
    )

    asyncio.run(
        health.check_configured_ai_api(
            config,
            cast("StartupNoticeService", _StartupNoticeRecorder()),
        )
    )

    assert received == [
        AiApiSettings(
            api_key="test-key",
            base_url="https://example.test/v1",
            model="test-model",
            timeout=10,
            thinking=False,
        )
    ]


def test_failed_ai_key_check_is_added_to_startup_notice(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_check(_settings: AiApiSettings) -> AiApiTestResult:
        return AiApiTestResult(
            ok=False,
            elapsed_ms=31,
            status_code=401,
            error="认证失败：invalid API key",
        )

    recorder = _StartupNoticeRecorder()
    monkeypatch.setattr(health, "check_ai_api", fake_check)

    asyncio.run(
        health.check_configured_ai_api(
            AiConfig(api_key="test-key"),
            cast("StartupNoticeService", recorder),
        )
    )

    assert recorder.parts == [
        (
            "startup_ai_api_check",
            "AI API startup check",
            "AI API Key 检查失败。\n"
            "模型：deepseek-v4-pro\n"
            "详情：认证失败：invalid API key",
        )
    ]


def test_missing_ai_key_skips_startup_check(monkeypatch: MonkeyPatch) -> None:
    async def unexpected_check(_settings: AiApiSettings) -> AiApiTestResult:
        raise AssertionError

    monkeypatch.setattr(health, "check_ai_api", unexpected_check)

    asyncio.run(
        health.check_configured_ai_api(
            AiConfig(),
            cast("StartupNoticeService", _StartupNoticeRecorder()),
        )
    )
