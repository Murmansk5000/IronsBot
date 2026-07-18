# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from .service import FeatureService


def event_has_feature(
    features: FeatureService,
    event: Event,
    feature: str,
) -> bool:
    if isinstance(event, GroupMessageEvent):
        return features.group_has_feature(event.group_id, feature)

    if isinstance(event, PrivateMessageEvent):
        return features.is_private_feature_allowed(event.user_id, feature)

    return False
