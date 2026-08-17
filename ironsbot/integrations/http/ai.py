# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from time import perf_counter
from typing import TYPE_CHECKING, Any

import httpx

from ironsbot.services.ai.responses import (
    AiRequestAttempt,
    AiResponseResult,
    parse_ai_response,
)

if TYPE_CHECKING:
    from ironsbot.config.models.ai import AiConfig
    from ironsbot.services.ai.history import HistoryMessage

AI_TEST_PROMPT = "请只回复 OK"
AI_MODELS_EMPTY_ERROR = "AI model list is empty"
logger = logging.getLogger(__name__)


class HttpAiCompletionClient:
    def __init__(self, client: httpx.AsyncClient, config: AiConfig) -> None:
        self._client = client
        self._config = config

    async def complete(
        self,
        messages: list[HistoryMessage],
    ) -> AiResponseResult:
        attempts: list[AiRequestAttempt] = []
        last_failure: AiResponseResult | None = None

        for endpoint in self._config.configured_endpoints:
            for model in endpoint.models:
                try:
                    response = await self._client.post(
                        f"{endpoint.base_url}/chat/completions",
                        headers=_authorization_headers(endpoint.api_key),
                        json=_completion_payload(self._config, messages, model=model),
                        timeout=self._config.timeout,
                        follow_redirects=True,
                    )
                except httpx.TimeoutException as exc:
                    last_failure = AiResponseResult(
                        status_code=0,
                        endpoint=endpoint.name,
                        model=model,
                        error_kind="timeout",
                        error_title="接口响应超时",
                        error_detail=str(exc) or "请求超时",
                    )
                    attempts.append(_attempt_from_result(last_failure))
                    logger.warning(
                        "AI endpoint timed out: endpoint=%s model=%s",
                        endpoint.name,
                        model,
                    )
                    break
                except httpx.HTTPError as exc:
                    last_failure = AiResponseResult(
                        status_code=0,
                        endpoint=endpoint.name,
                        model=model,
                        error_kind="network",
                        error_title="网络请求失败",
                        error_detail=str(exc),
                    )
                    attempts.append(_attempt_from_result(last_failure))
                    logger.warning(
                        "AI endpoint request failed: endpoint=%s model=%s error=%s",
                        endpoint.name,
                        model,
                        exc,
                    )
                    break

                result = replace(
                    _parse_http_response(response),
                    endpoint=endpoint.name,
                    model=model,
                )
                if result.ok:
                    return replace(result, attempts=tuple(attempts))
                last_failure = result
                attempts.append(_attempt_from_result(result))
                logger.warning(
                    "AI model returned an error: endpoint=%s model=%s HTTP=%s "
                    "detail=%s",
                    endpoint.name,
                    model,
                    result.status_code,
                    result.error_detail,
                )
                if _should_switch_endpoint(result):
                    break

        if last_failure is not None:
            return replace(last_failure, attempts=tuple(attempts))
        return AiResponseResult(
            status_code=0,
            error_kind="network",
            error_title="AI 没有可用端点",
            error_detail=AI_MODELS_EMPTY_ERROR,
        )


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


async def check_ai_api(settings: AiApiSettings) -> AiApiTestResult:
    if not settings.api_key:
        return AiApiTestResult(
            ok=False,
            elapsed_ms=0,
            error="未配置 AI_KEY",
        )

    started_at = perf_counter()
    base_url = settings.base_url.strip().rstrip("/")

    try:
        async with httpx.AsyncClient(
            timeout=settings.timeout,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=_authorization_headers(settings.api_key),
                json=_test_payload(settings),
            )
    except httpx.TimeoutException:
        return AiApiTestResult(
            ok=False,
            elapsed_ms=_elapsed_ms(started_at),
            error=f"请求超时（{settings.timeout} 秒）",
        )
    except httpx.HTTPError as exc:
        return AiApiTestResult(
            ok=False,
            elapsed_ms=_elapsed_ms(started_at),
            error=f"网络请求失败：{exc}",
        )

    elapsed_ms = _elapsed_ms(started_at)
    parsed = _parse_http_response(response)
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


def _authorization_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }


def _completion_payload(
    config: AiConfig,
    messages: list[HistoryMessage],
    *,
    model: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "stream": False,
        "thinking": {
            "type": "enabled" if config.thinking else "disabled",
        },
    }


def _attempt_from_result(result: AiResponseResult) -> AiRequestAttempt:
    return AiRequestAttempt(
        endpoint=result.endpoint,
        model=result.model,
        status_code=result.status_code or None,
        error_title=result.error_title,
        error_detail=result.error_detail,
    )


def _should_switch_endpoint(result: AiResponseResult) -> bool:
    return result.status_code in {401, 402, 403, 429} or result.status_code >= 500  # noqa: PLR2004


def _test_payload(settings: AiApiSettings) -> dict[str, Any]:
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
            "type": "enabled" if settings.thinking else "disabled",
        },
    }


def _parse_http_response(response: httpx.Response) -> AiResponseResult:
    try:
        data: object = response.json()
    except ValueError:
        return parse_ai_response(
            response.status_code,
            None,
            raw_text=response.text,
            valid_json=False,
        )
    return parse_ai_response(
        response.status_code,
        data,
        raw_text=response.text,
    )


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)
