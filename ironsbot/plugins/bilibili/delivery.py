from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger

from ironsbot.services.bilibili.parser import (
    dynamic_content,
    dynamic_image_urls,
    dynamic_url,
    item_author_label,
)


def build_dynamic_link_message(
    item: dict[str, Any],
    pub_ts: int,
) -> Message | None:
    try:
        time_str = datetime.fromtimestamp(
            pub_ts,
            tz=timezone.utc,
        ).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        return Message(
            MessageSegment.text(
                "🔔 【B站动态更新】\n"
                f"👤 账号：{item_author_label(item)}\n"
                f"⏰ 发布时间：{time_str}\n\n"
                f"传送门：{dynamic_url(item)}"
            )
        )
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
