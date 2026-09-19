# SPDX-License-Identifier: MIT
"""Redact transport identities and deployment secrets from every Loguru sink."""

from __future__ import annotations

import hashlib
import re
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.log import logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from loguru import Record

_SECRET_ENV_MARKERS = ("APP_ID", "KEY", "PASSWORD", "SECRET", "TOKEN")
_MIN_SECRET_LENGTH = 6
_OPENID_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-F0-9]{32}(?![A-Za-z0-9])")
_NUMERIC_ID_PATTERN = re.compile(r"(?<![A-Za-z0-9])\d{7,}(?![A-Za-z0-9])")


@dataclass(frozen=True, slots=True)
class LogPrivacyRedactor:
    secrets: tuple[str, ...]

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> LogPrivacyRedactor:
        values = {
            str(value)
            for name, value in env.items()
            if any(marker in name.upper() for marker in _SECRET_ENV_MARKERS)
            and len(str(value)) >= _MIN_SECRET_LENGTH
        }
        return cls(tuple(sorted(values, key=len, reverse=True)))

    def __call__(self, record: Record) -> None:
        message = self.redact(str(record["message"]))
        exception = record["exception"]
        if exception is not None:
            rendered = "".join(
                traceback.format_exception(
                    exception.type,
                    exception.value,
                    exception.traceback,
                )
            )
            message = f"{message}\n{self.redact(rendered)}"
            record["exception"] = None
        record["message"] = message

    def redact(self, value: str) -> str:
        redacted = value
        for secret in self.secrets:
            redacted = redacted.replace(secret, _digest_label("secret", secret))
        redacted = _OPENID_PATTERN.sub(
            lambda match: _digest_label("openid", match.group()),
            redacted,
        )
        return _NUMERIC_ID_PATTERN.sub(
            lambda match: _digest_label("id", match.group()),
            redacted,
        )


def configure_log_privacy(env: Mapping[str, str]) -> None:
    logger.configure(patcher=LogPrivacyRedactor.from_environment(env))


def _digest_label(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"<{kind}:{digest}>"
