# SPDX-License-Identifier: MIT
"""Bounded failure explanations suitable for logs and administrator notices."""

from __future__ import annotations

import re

_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_SECRET = re.compile(
    r"(?i)\b(authorization|bearer|token|secret|signature|upload_id|file_info|"
    r"access_token|app_secret|password)\b[\s\"':=]+[^\s,;<>]+"
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_+/=.-]{24,}|\b\d{6,}\b")


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
