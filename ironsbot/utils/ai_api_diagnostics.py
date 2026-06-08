# SPDX-License-Identifier: MIT
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx

AI_TEST_PROMPT = "请只回复 OK"
HTTP_BAD_REQUEST = 400
HTTP_PAYMENT_REQUIRED = 402
HTTP_TOO_MANY_REQUESTS = 429


@dataclass(frozen=True, slots=True)
class AiApiSettings:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    timeout: float = 45.0
    thinking: bool = False


@dataclass(frozen=True, slots=True)
class AiApiTestResult:
    ok: bool
    elapsed_ms: int
    status_code: int | None = None
    reply: str = ""
    error: str = ""


def _extract_reply(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""

    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, str):
        return content.strip()

    return ""


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:300]

    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("code") or str(error)
        return str(message)[:300]

    return str(data)[:300]


def _api_error_title(status_code: int) -> str:
    if status_code in {401, 403}:
        return "密钥错误或没有接口权限"

    if status_code == HTTP_PAYMENT_REQUIRED:
        return "API额度不足或账户余额不足"

    if status_code == HTTP_TOO_MANY_REQUESTS:
        return "请求过于频繁或触发限流"

    return "接口返回异常"


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


async def check_ai_api(settings: AiApiSettings) -> AiApiTestResult:  # noqa: PLR0911
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
    if response.status_code >= HTTP_BAD_REQUEST:
        return AiApiTestResult(
            ok=False,
            elapsed_ms=elapsed_ms,
            status_code=response.status_code,
            error=(
                f"{_api_error_title(response.status_code)}："
                f"{_extract_error_detail(response)}"
            ),
        )

    try:
        data = response.json()
    except ValueError:
        return AiApiTestResult(
            ok=False,
            elapsed_ms=elapsed_ms,
            status_code=response.status_code,
            error=f"接口返回成功，但响应不是有效 JSON：{response.text[:120]}",
        )

    reply = _extract_reply(data)
    if not reply:
        return AiApiTestResult(
            ok=False,
            elapsed_ms=elapsed_ms,
            status_code=response.status_code,
            error="接口返回成功，但没有有效文本内容",
        )

    return AiApiTestResult(
        ok=True,
        elapsed_ms=elapsed_ms,
        status_code=response.status_code,
        reply=reply,
    )
