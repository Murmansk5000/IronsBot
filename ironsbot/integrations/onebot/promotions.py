# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Protocol

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.features import FIRE_MANUAL_AD_FEATURE
from ironsbot.core.messaging import MessageTarget, append_fire_manual_ad_text


class OneBotTargetFeaturePolicy(Protocol):
    """Feature checks expressed in the OneBot numeric target model."""

    def group_has_feature(self, group_id: int, feature: str) -> bool: ...

    def users_for_feature(self, feature: str) -> list[int]: ...


def fire_manual_ad_enabled_for_target(
    features: OneBotTargetFeaturePolicy,
    target: MessageTarget,
) -> bool:
    """Whether this OneBot target has opted into the promotion feature."""

    if target.target_type == "group":
        return features.group_has_feature(target.target_id, FIRE_MANUAL_AD_FEATURE)
    return target.target_id in features.users_for_feature(FIRE_MANUAL_AD_FEATURE)


def append_fire_manual_ad_for_target(
    features: OneBotTargetFeaturePolicy,
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
