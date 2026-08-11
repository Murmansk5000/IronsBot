from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger

from ironsbot.services.bilibili.parser import (
    dynamic_content,
    dynamic_image_urls,
    dynamic_url,
    item_author_mid,
    item_author_name,
)


def build_dynamic_link_message(
    item: dict[str, Any],
    pub_ts: int,
) -> Message | None:
    try:
        author_name = item_author_name(item)
        author_mid = item_author_mid(item)
        time_str = datetime.fromtimestamp(
            pub_ts,
            tz=timezone.utc,
        ).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        return Message(
            MessageSegment.text(
                f"🔔 【{author_name}】发布了一条B站动态\n"
                f"👤 UID：{author_mid or '未知'}\n"
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


def build_dynamic_images_message(item: dict[str, Any]) -> Message | None:
    """Render only a dynamic's images for the second full-push message."""

    try:
        message = Message()
        for image_url in dynamic_image_urls(item):
            sanitized_url = image_url.strip().rstrip("]")
            if not sanitized_url:
                continue
            if message:
                message += MessageSegment.text("\n")
            message += MessageSegment.image(sanitized_url)
    except (TypeError, ValueError, KeyError) as error:
        logger.error(f"failed to render Bilibili dynamic images: {error}")
        return None
    return message or None


def build_dynamic_text_message(
    item: dict[str, Any],
    content_override: str | None = None,
) -> Message | None:
    """Render only a dynamic's body or AI summary for the final full push."""

    try:
        content = (content_override or dynamic_content(item)).strip()
        return Message(MessageSegment.text(content)) if content else None
    except (TypeError, ValueError, KeyError) as error:
        logger.error(f"failed to render Bilibili dynamic text: {error}")
        return None


def build_dynamic_detail_messages(item: dict[str, Any]) -> tuple[Message, ...]:
    """Render a history detail with text and images as separate messages."""

    messages = (
        build_dynamic_text_message(item),
        build_dynamic_images_message(item),
    )
    return tuple(message for message in messages if message is not None)
