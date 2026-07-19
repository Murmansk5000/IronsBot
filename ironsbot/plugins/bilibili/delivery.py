from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger

from ironsbot.services.bilibili.parser import (
    dynamic_content,
    dynamic_image_urls,
    dynamic_url,
    item_author_label,
)

if TYPE_CHECKING:
    from ironsbot.services.bilibili.delivery import DynamicRenderMode

MAX_DYNAMIC_CONTENT_CHARS = 500


def build_dynamic_message(
    item: dict[str, Any],
    pub_ts: int,
    mode: DynamicRenderMode = "full",
    *,
    menu_mode: bool = False,
) -> Message | None:
    try:
        time_str = datetime.fromtimestamp(
            pub_ts,
            tz=timezone.utc,
        ).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        tag = "B站点播详情" if menu_mode else "B站动态更新"
        message = Message(
            MessageSegment.text(
                f"🔔 【{tag}】\n"
                f"👤 账号：{item_author_label(item)}\n"
                f"⏰ 发布时间: {time_str}\n\n"
            )
        )
        if mode == "full":
            content = dynamic_content(item)
            if len(content) > MAX_DYNAMIC_CONTENT_CHARS:
                content = f"{content[:MAX_DYNAMIC_CONTENT_CHARS]}..."
            message += MessageSegment.text(f"{content}\n")
            for image_url in dynamic_image_urls(item):
                sanitized_url = image_url.strip().rstrip("]")
                if sanitized_url:
                    message += MessageSegment.image(sanitized_url)
                    message += MessageSegment.text("\n")
        message += MessageSegment.text(f"传送门: {dynamic_url(item)}")
    except (TypeError, ValueError, KeyError) as error:
        logger.error(f"failed to render Bilibili dynamic: {error}")
        return None
    return message
