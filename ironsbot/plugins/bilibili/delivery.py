from __future__ import annotations

from typing import Any

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger

from ironsbot.services.bilibili.parser import (
    dynamic_content,
    dynamic_image_urls,
    dynamic_url,
)


def build_dynamic_link_message(item: dict[str, Any]) -> Message | None:
    try:
        return Message(MessageSegment.text(f"传送门: {dynamic_url(item)}"))
    except (TypeError, ValueError, KeyError) as error:
        logger.error(f"failed to render Bilibili dynamic link: {error}")
        return None


def build_dynamic_content_message(
    item: dict[str, Any],
    content_override: str | None = None,
) -> Message | None:
    """Render only a dynamic's content and images, without duplicate metadata."""
    try:
        message = Message()
        content = (content_override or dynamic_content(item)).strip()
        if content:
            message += MessageSegment.text(content)
        for image_url in dynamic_image_urls(item):
            sanitized_url = image_url.strip().rstrip("]")
            if not sanitized_url:
                continue
            if message:
                message += MessageSegment.text("\n")
            message += MessageSegment.image(sanitized_url)
    except (TypeError, ValueError, KeyError) as error:
        logger.error(f"failed to render Bilibili dynamic content: {error}")
        return None
    else:
        return message or None
