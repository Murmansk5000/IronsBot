# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.features import FIRE_MANUAL_AD_FEATURE
from ironsbot.core.messaging import (
    FIRE_MANUAL_LINK_MESSAGE,
    FIRE_MANUAL_URL,
    append_fire_manual_ad_text,
)

if TYPE_CHECKING:
    from ironsbot.shared.features import FeatureService


def append_fire_manual_ad_message(message: Message) -> Message:
    if FIRE_MANUAL_URL in str(message):
        return message
    message += MessageSegment.text(f"\n\n{FIRE_MANUAL_LINK_MESSAGE}")
    return message


def fire_manual_ad_enabled_for_group(
    features: FeatureService,
    group_id: int | None,
) -> bool:
    if group_id is None:
        return True
    return features.group_has_feature(group_id, FIRE_MANUAL_AD_FEATURE)


def append_fire_manual_ad_for_group(
    features: FeatureService,
    message: str | Message,
    group_id: int | None,
) -> str | Message:
    if not fire_manual_ad_enabled_for_group(features, group_id):
        return message
    if isinstance(message, Message):
        return append_fire_manual_ad_message(message)
    return append_fire_manual_ad_text(message)


def split_fire_manual_ad_group_ids(
    features: FeatureService,
    group_ids: list[int],
) -> tuple[list[int], list[int]]:
    enabled: list[int] = []
    disabled: list[int] = []
    for group_id in group_ids:
        if fire_manual_ad_enabled_for_group(features, group_id):
            enabled.append(group_id)
        else:
            disabled.append(group_id)
    return enabled, disabled
