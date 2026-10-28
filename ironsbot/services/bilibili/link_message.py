# SPDX-License-Identifier: MIT
"""Portable reminder content, independent of delivery lifecycle orchestration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.time import TZ_CN
from ironsbot.services.bilibili.parser import (
    dynamic_url,
    item_author_mid,
    item_author_name,
)

_LOGGER = logging.getLogger(__name__)


def render_dynamic_link_message(
    item: dict[str, Any], pub_ts: int, *, fallback_name: str | None = None
) -> OutboundMessage | None:
    try:
        author_name = item_author_name(item)
        author_mid = item_author_mid(item)
        if fallback_name and author_name in {f"UID {author_mid}", "该账号"}:
            author_name = fallback_name
        time_str = datetime.fromtimestamp(pub_ts, tz=TZ_CN).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        return OutboundMessage(
            (
                TextPart(
                    f"🔔 【{author_name}】发布了一条B站动态\n"
                    f"👤 UID：{author_mid or '未知'}\n"
                    f"⏰ 发布时间：{time_str}\n\n"
                    f"传送门：{dynamic_url(item)}"
                ),
            )
        )
    except (TypeError, ValueError, KeyError):
        _LOGGER.exception("failed to render Bilibili dynamic link")
        return None
