# SPDX-License-Identifier: MIT
from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

UNITY_NOTICE_URL = "https://unity-notice.61.com/unity_notice/"
UNITY_NOTICE_CACHE_TTL = timedelta(minutes=30)
UNITY_NOTICE_ERROR_TTL = timedelta(minutes=5)
_LOGGER = logging.getLogger(__name__)


def normalize_notice_text(text_value: str) -> str:
    return html.unescape(
        text_value
        .replace("\\r", "\n")
        .replace("\\n", "\n")
        .replace("\\/", "/")
    )


@dataclass(slots=True)
class UnityNoticeSource:
    client: httpx.Client
    text: str = ""
    expires_at: datetime | None = None

    def fetch(self, now: datetime) -> str:
        if self.expires_at is not None and self.expires_at > now:
            return self.text

        try:
            response = self.client.get(UNITY_NOTICE_URL)
            response.raise_for_status()
        except (OSError, httpx.HTTPError) as exc:
            _LOGGER.warning("activity notice fetch failed: %s", exc)
            self.expires_at = now + UNITY_NOTICE_ERROR_TTL
            return self.text

        self.text = normalize_notice_text(
            response.content.decode("utf-8", "replace")
        )
        self.expires_at = now + UNITY_NOTICE_CACHE_TTL
        return self.text
