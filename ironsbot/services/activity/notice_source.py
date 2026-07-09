# SPDX-License-Identifier: MIT
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from nonebot.log import logger

from ironsbot.config.loader import get_app_config

UNITY_NOTICE_URL = "https://unity-notice.61.com/unity_notice/"
UNITY_NOTICE_CACHE_TTL = timedelta(minutes=30)


@dataclass(slots=True)
class NoticeCache:
    text: str = ""
    expires_at: datetime | None = None


_notice_cache = NoticeCache()


def normalize_notice_text(text_value: str) -> str:
    return html.unescape(
        text_value
        .replace("\\r", "\n")
        .replace("\\n", "\n")
        .replace("\\/", "/")
    )


def fetch_unity_notice_text(now: datetime) -> str:
    if (
        _notice_cache.expires_at is not None
        and _notice_cache.expires_at > now
    ):
        return _notice_cache.text

    try:
        response = httpx.get(
            UNITY_NOTICE_URL,
            headers={"User-Agent": "IronsBot activity reminder"},
            timeout=get_app_config().activity.notice_timeout_seconds,
        )
        response.raise_for_status()
        raw_text = response.content.decode("utf-8", "replace")
    except (OSError, httpx.HTTPError) as e:
        logger.warning(f"activity notice fetch failed: {e}")
        _notice_cache.expires_at = now + timedelta(minutes=5)
        return _notice_cache.text

    _notice_cache.text = normalize_notice_text(raw_text)
    _notice_cache.expires_at = now + UNITY_NOTICE_CACHE_TTL
    return _notice_cache.text
