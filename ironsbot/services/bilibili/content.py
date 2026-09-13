# SPDX-License-Identifier: MIT
"""Shared long-form Bilibili content compaction."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

SUMMARY_MAX_ATTEMPTS = 3
AI_SUMMARY_PREFIX = "本条动态文本过长，AI总结如下：\n"
_LOGGER = logging.getLogger(__name__)


class DynamicSummarizer(Protocol):
    async def __call__(self, text: str, *, max_chars: int) -> str | None: ...


@dataclass(frozen=True, slots=True)
class CompactedDynamicContent:
    text: str
    generated_by_ai: bool

    @property
    def display_text(self) -> str:
        if self.generated_by_ai:
            return f"{AI_SUMMARY_PREFIX}{self.text}"
        return self.text


@dataclass(frozen=True, slots=True)
class DynamicContentCompactor:
    """Compact long content once for push and history consumers."""

    summarizer: DynamicSummarizer | None
    content_max_chars: int
    summary_max_chars: int
    use_ai: bool

    async def compact(self, content: str) -> CompactedDynamicContent | None:
        if len(content) <= self.content_max_chars:
            return None
        if self.use_ai and self.summarizer is not None:
            for attempt in range(1, SUMMARY_MAX_ATTEMPTS + 1):
                try:
                    summary = await self.summarizer(
                        content,
                        max_chars=self.summary_max_chars,
                    )
                except Exception as error:  # noqa: BLE001 - optional AI fallback
                    _LOGGER.warning(
                        "Bilibili summary attempt %s/%s failed: %s",
                        attempt,
                        SUMMARY_MAX_ATTEMPTS,
                        type(error).__name__,
                    )
                    continue
                if summary and len(summary.strip()) <= self.summary_max_chars:
                    return CompactedDynamicContent(
                        text=summary.strip(),
                        generated_by_ai=True,
                    )
                _LOGGER.warning(
                    "Bilibili summary attempt %s/%s returned unusable content",
                    attempt,
                    SUMMARY_MAX_ATTEMPTS,
                )
        return CompactedDynamicContent(
            text=content[: self.summary_max_chars].rstrip(),
            generated_by_ai=False,
        )
