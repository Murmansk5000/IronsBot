# SPDX-License-Identifier: MIT
"""Read-only HTTPS Date-header sampling for local clock diagnostics."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

logger = logging.getLogger(__name__)
UTC = timezone.utc
DEFAULT_CLOCK_CHECK_URLS = (
    "https://api.github.com",
    "https://www.bilibili.com",
    "https://www.baidu.com",
)


@dataclass(frozen=True, slots=True)
class ClockCheckSample:
    url: str
    offset_seconds: float


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def check_clock_drift(
    *,
    timeout_seconds: float,
    urls: Sequence[str] = DEFAULT_CLOCK_CHECK_URLS,
    client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    now: Callable[[], datetime] = _utc_now,
) -> tuple[ClockCheckSample, ...]:
    """Estimate local-clock offset from HTTPS Date headers without changing time."""

    async def fetch(url: str) -> ClockCheckSample | None:
        started_at = now()
        try:
            async with client_factory(
                follow_redirects=True,
                timeout=timeout_seconds,
            ) as client:
                response = await client.head(url)
        except httpx.HTTPError as exc:
            logger.warning("clock check source failed: %s: %s", url, exc)
            return None
        ended_at = now()
        date_value = response.headers.get("Date")
        if not date_value:
            logger.warning("clock check source omitted Date header: %s", url)
            return None
        try:
            source_time = parsedate_to_datetime(date_value).astimezone(UTC)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "clock check source has invalid Date header: %s: %s",
                url,
                exc,
            )
            return None
        midpoint = started_at + (ended_at - started_at) / 2
        return ClockCheckSample(url, (source_time - midpoint).total_seconds())

    samples = await asyncio.gather(*(fetch(url) for url in urls))
    return tuple(sample for sample in samples if sample is not None)
