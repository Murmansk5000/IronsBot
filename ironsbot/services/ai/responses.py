# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import httpx

HTTP_BAD_REQUEST = 400
HTTP_PAYMENT_REQUIRED = 402
HTTP_TOO_MANY_REQUESTS = 429

AiResponseErrorKind = Literal["http", "invalid_json", "empty_reply"]


@dataclass(frozen=True, slots=True)
class AiResponseResult:
    status_code: int
    reply: str = ""
    error_kind: AiResponseErrorKind | None = None
    error_title: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.error_kind is None


def extract_ai_reply(data: object) -> str:
    if not isinstance(data, dict):
        return ""

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    choice = choices[0]
    if not isinstance(choice, dict):
        return ""

    message = choice.get("message")
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    return content.strip() if isinstance(content, str) else ""


def ai_api_error_title(status_code: int) -> str:
    if status_code in {401, 403}:
        return "密钥错误或没有接口权限"
    if status_code == HTTP_PAYMENT_REQUIRED:
        return "API额度不足或账户余额不足"
    if status_code == HTTP_TOO_MANY_REQUESTS:
        return "请求过于频繁或触发限流"
    return "接口返回异常"


def parse_ai_response(response: httpx.Response) -> AiResponseResult:
    if response.status_code >= HTTP_BAD_REQUEST:
        return AiResponseResult(
            status_code=response.status_code,
            error_kind="http",
            error_title=ai_api_error_title(response.status_code),
            error_detail=_extract_error_detail(response),
        )

    try:
        data: object = response.json()
    except ValueError:
        return AiResponseResult(
            status_code=response.status_code,
            error_kind="invalid_json",
            error_title="接口响应不是有效 JSON",
            error_detail=response.text[:300],
        )

    reply = extract_ai_reply(data)
    if not reply:
        return AiResponseResult(
            status_code=response.status_code,
            error_kind="empty_reply",
            error_title="接口返回空内容",
            error_detail="choices[0].message.content 缺失或为空",
        )

    return AiResponseResult(status_code=response.status_code, reply=reply)


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        data: object = response.json()
    except ValueError:
        return response.text[:300]

    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or str(error)
            return str(message)[:300]
    return str(data)[:300]


__all__ = [
    "AiResponseErrorKind",
    "AiResponseResult",
    "ai_api_error_title",
    "extract_ai_reply",
    "parse_ai_response",
]
