# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

HTTP_BAD_REQUEST = 400
HTTP_PAYMENT_REQUIRED = 402
HTTP_TOO_MANY_REQUESTS = 429

AiResponseErrorKind = Literal[
    "http",
    "invalid_json",
    "empty_reply",
    "network",
    "timeout",
]


@dataclass(frozen=True, slots=True)
class AiRequestAttempt:
    endpoint: str
    model: str
    status_code: int | None = None
    error_title: str = ""
    error_detail: str = ""


@dataclass(frozen=True, slots=True)
class AiResponseResult:
    status_code: int
    reply: str = ""
    endpoint: str = ""
    model: str = ""
    error_kind: AiResponseErrorKind | None = None
    error_title: str = ""
    error_detail: str = ""
    attempts: tuple[AiRequestAttempt, ...] = ()

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


def parse_ai_response(
    status_code: int,
    data: object,
    *,
    raw_text: str = "",
    valid_json: bool = True,
) -> AiResponseResult:
    if status_code >= HTTP_BAD_REQUEST:
        return AiResponseResult(
            status_code=status_code,
            error_kind="http",
            error_title=ai_api_error_title(status_code),
            error_detail=_extract_error_detail(data, raw_text),
        )

    if not valid_json:
        return AiResponseResult(
            status_code=status_code,
            error_kind="invalid_json",
            error_title="接口响应不是有效 JSON",
            error_detail=raw_text[:300],
        )

    reply = extract_ai_reply(data)
    if not reply:
        return AiResponseResult(
            status_code=status_code,
            error_kind="empty_reply",
            error_title="接口返回空内容",
            error_detail="choices[0].message.content 缺失或为空",
        )

    return AiResponseResult(status_code=status_code, reply=reply)


def _extract_error_detail(data: object, raw_text: str) -> str:
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or str(error)
            return str(message)[:300]
        return str(data)[:300]
    return raw_text[:300]
