# SPDX-License-Identifier: MIT
"""Local resource readers derived from htmlkit's MIT Python adapter."""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from urllib.parse import unquote

logger = logging.getLogger(__name__)


async def local_image(url: str) -> bytes | None:
    try:
        if url.startswith("data:"):
            header, data = url.split(",", 1)
            return (
                base64.b64decode(data)
                if "base64" in header
                else unquote(data).encode("utf-8")
            )
        if url.startswith("file://"):
            return await asyncio.to_thread(Path(url[7:]).read_bytes)
    except (ValueError, OSError) as error:
        logger.warning("local render image failed: %s", type(error).__name__)
    return None


async def local_css(url: str) -> str | None:
    try:
        if url.startswith("data:"):
            header, data = url.split(",", 1)
            return (
                base64.b64decode(data).decode("utf-8")
                if "base64" in header
                else unquote(data)
            )
        if url.startswith("file://"):
            return await asyncio.to_thread(Path(url[7:]).read_text, encoding="utf-8")
    except (ValueError, OSError) as error:
        logger.warning("local render CSS failed: %s", type(error).__name__)
    return None
