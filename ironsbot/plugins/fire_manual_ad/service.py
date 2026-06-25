# SPDX-License-Identifier: MIT
from __future__ import annotations

from nonebot.adapters.onebot.v11 import Message, MessageSegment

FIRE_MANUAL_URL = "https://seerinfo.yuyuqaq.cn/firedict"
FIRE_MANUAL_LINK_MESSAGE = f"火火手册链接：{FIRE_MANUAL_URL}"


def append_fire_manual_ad_text(message: str) -> str:
    text = message.rstrip()
    if FIRE_MANUAL_URL in text:
        return text
    if not text:
        return FIRE_MANUAL_LINK_MESSAGE
    return f"{text}\n\n{FIRE_MANUAL_LINK_MESSAGE}"


def append_fire_manual_ad_message(message: Message) -> Message:
    if FIRE_MANUAL_URL in str(message):
        return message
    message += MessageSegment.text(f"\n\n{FIRE_MANUAL_LINK_MESSAGE}")
    return message


__all__ = [
    "FIRE_MANUAL_LINK_MESSAGE",
    "FIRE_MANUAL_URL",
    "append_fire_manual_ad_message",
    "append_fire_manual_ad_text",
]

