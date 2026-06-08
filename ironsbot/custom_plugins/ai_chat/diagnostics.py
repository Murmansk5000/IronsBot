from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx

from .client import _api_error_title, _extract_error_detail, _extract_reply
from .config import plugin_config

AI_TEST_PROMPT = "请只回复 OK"
HTTP_BAD_REQUEST = 400


@dataclass(frozen=True, slots=True)
class AiApiTestResult:
    ok: bool
    elapsed_ms: int
    status_code: int | None = None
    reply: str = ""
    error: str = ""


def is_ai_test_command(text: str) -> bool:
    normalized = "".join(text.split()).lower()
    return normalized in {
        "/ai测试",
        "/ai接口测试",
        "/测试ai",
        "/测试ai接口",
    }


def _build_test_payload() -> dict[str, Any]:
    return {
        "model": plugin_config.ai_model,
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
            "type": "enabled" if plugin_config.ai_thinking else "disabled"
        },
    }


async def test_ai_api() -> AiApiTestResult:
    started_at = perf_counter()
    headers = {
        "Authorization": f"Bearer {plugin_config.ai_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(
            timeout=plugin_config.ai_timeout,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                f"{plugin_config.ai_base_url}/chat/completions",
                headers=headers,
                json=_build_test_payload(),
            )
    except httpx.TimeoutException:
        return AiApiTestResult(
            ok=False,
            elapsed_ms=int((perf_counter() - started_at) * 1000),
            error=f"请求超时（{plugin_config.ai_timeout} 秒）",
        )
    except httpx.HTTPError as e:
        return AiApiTestResult(
            ok=False,
            elapsed_ms=int((perf_counter() - started_at) * 1000),
            error=f"网络请求失败：{e}",
        )

    elapsed_ms = int((perf_counter() - started_at) * 1000)
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
