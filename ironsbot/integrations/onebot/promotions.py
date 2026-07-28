# SPDX-License-Identifier: MIT
from __future__ import annotations

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.messaging import MessageTarget, append_fire_manual_ad_text
from ironsbot.services.messaging.promotions import (
    TargetFeaturePolicy,
    fire_manual_ad_enabled_for_target,
)


def append_fire_manual_ad_for_target(
    features: TargetFeaturePolicy,
    message: str | Message,
    target: MessageTarget,
) -> str | Message:
    """Append the Fire Manual link only for this delivery target."""

    if not fire_manual_ad_enabled_for_target(features, target):
        return message
    if isinstance(message, Message):
        if "https://seerinfo.yuyuqaq.cn/firedict" in str(message):
            return message
        return Message(message) + MessageSegment.text(
            "\n\n火火手册链接：https://seerinfo.yuyuqaq.cn/firedict"
        )
    return append_fire_manual_ad_text(message)
