# SPDX-License-Identifier: MIT
from __future__ import annotations

from nonebot.adapters.onebot.v11 import Message, MessageSegment

FIRE_MANUAL_FEATURE = "fire_manual"
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


def fire_manual_ad_enabled_for_group(group_id: int | None) -> bool:
    if group_id is None:
        return True

    from ironsbot.shared.features import group_has_feature

    return group_has_feature(group_id, FIRE_MANUAL_FEATURE)


def append_fire_manual_ad_for_group(
    message: str | Message,
    group_id: int | None,
) -> str | Message:
    if not fire_manual_ad_enabled_for_group(group_id):
        return message
    if isinstance(message, Message):
        return append_fire_manual_ad_message(message)
    return append_fire_manual_ad_text(message)


def split_fire_manual_ad_group_ids(
    group_ids: list[int],
) -> tuple[list[int], list[int]]:
    enabled: list[int] = []
    disabled: list[int] = []
    for group_id in group_ids:
        if fire_manual_ad_enabled_for_group(group_id):
            enabled.append(group_id)
        else:
            disabled.append(group_id)
    return enabled, disabled


__all__ = [
    "FIRE_MANUAL_FEATURE",
    "FIRE_MANUAL_LINK_MESSAGE",
    "FIRE_MANUAL_URL",
    "append_fire_manual_ad_for_group",
    "append_fire_manual_ad_message",
    "append_fire_manual_ad_text",
    "fire_manual_ad_enabled_for_group",
    "split_fire_manual_ad_group_ids",
]
