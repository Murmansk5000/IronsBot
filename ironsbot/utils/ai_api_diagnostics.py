# SPDX-License-Identifier: MIT
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx

from ironsbot.services.ai.responses import parse_ai_response

AI_TEST_PROMPT = "请只回复 OK"


@dataclass(frozen=True, slots=True)
class AiApiSettings:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-pro"
    timeout: float = 45.0
    thinking: bool = False


@dataclass(frozen=True, slots=True)
class AiApiTestResult:
    ok: bool
    elapsed_ms: int
    status_code: int | None = None
    reply: str = ""
    error: str = ""


def _build_test_payload(settings: AiApiSettings) -> dict[str, Any]:
    return {
        "model": settings.model,
        "messages": [
            {
                "role": "system",
                "content": "You are an API health-check endpoint.",
            },
            {
                "role": "user",
                "content": AI_TEST_PROMPT,
            },
        ],
        "temperature": 0,
        "max_tokens": 16,
        "stream": False,
        "thinking": {
            "type": "enabled" if settings.thinking else "disabled"
        },
    }


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


async def check_ai_api(settings: AiApiSettings) -> AiApiTestResult:
    if not settings.api_key:
        return AiApiTestResult(
            ok=False,
            elapsed_ms=0,
            error="未配置 AI_KEY",
        )

    started_at = perf_counter()
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }
    base_url = settings.base_url.strip().rstrip("/")

    try:
        async with httpx.AsyncClient(
            timeout=settings.timeout,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=_build_test_payload(settings),
            )
    except httpx.TimeoutException:
        return AiApiTestResult(
            ok=False,
            elapsed_ms=_elapsed_ms(started_at),
            error=f"请求超时（{settings.timeout} 秒）",
        )
    except httpx.HTTPError as e:
        return AiApiTestResult(
            ok=False,
            elapsed_ms=_elapsed_ms(started_at),
            error=f"网络请求失败：{e}",
        )

    elapsed_ms = _elapsed_ms(started_at)
    parsed = parse_ai_response(response)
    if not parsed.ok:
        return AiApiTestResult(
            ok=False,
            elapsed_ms=elapsed_ms,
            status_code=parsed.status_code,
            error=f"{parsed.error_title}：{parsed.error_detail}",
        )

    return AiApiTestResult(
        ok=True,
        elapsed_ms=elapsed_ms,
        status_code=parsed.status_code,
        reply=parsed.reply,
    )
