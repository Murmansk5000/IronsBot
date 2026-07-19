# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from httpx import AsyncClient

NOTICE_URL = "https://unity-notice.61.com/unity_notice/"
NOTICE_MAINTENANCE_TYPE = 3
HTTP_TIMEOUT_SECONDS = 12.0
HTML_TAG_PATTERN = re.compile(r"<[^>]*>")


@dataclass(frozen=True, slots=True)
class HttpServerNoticeSource:
    client: AsyncClient

    async def fetch(self) -> str | None:
        response = await self.client.get(
            NOTICE_URL,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            return None

        for item in data:
            if not isinstance(item, dict):
                continue
            if item.get("type") == NOTICE_MAINTENANCE_TYPE:
                text = item.get("text")
                if isinstance(text, str):
                    return HTML_TAG_PATTERN.sub("", text).replace("\\n", "\n").strip()
        return None
