# SPDX-License-Identifier: MIT
"""Bounded platform explanations without identifiers or upload credentials."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_SECRET = re.compile(
    r"(?i)\b(authorization|bearer|token|secret|signature|upload_id|file_info|"
    r"access_token|app_secret|password)\b[\s\"':=]+[^\s,;<>]+"
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_+/=.-]{24,}|\b\d{6,}\b")
_ROUTE = re.compile(r"^/v2/(groups|users)/[^/]+/([a-z_]+)$")


def safe_platform_message(value: object, *, secrets: tuple[str, ...] = ()) -> str:
    if not isinstance(value, str) or not value.strip():
        return "平台未提供错误说明"
    text = value[:4096]
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    text = _URL.sub("[url omitted]", text)
    text = _SECRET.sub("[credential omitted]", text)
    text = _IDENTIFIER.sub("[identifier omitted]", text)
    return " ".join(text.split())[:256]


def request_endpoint(url: str) -> str:
    match = _ROUTE.fullmatch(urlsplit(url).path)
    if match is None:
        return "平台未提供接口模板"
    return f"/v2/{match[1]}/{{target}}/{match[2]}"
