# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

from .service import (
    group_has_feature,
    is_event_feature_allowed,
    is_private_feature_allowed,
)

if TYPE_CHECKING:
    from nonebot.adapters import Event


def feature_visible_for_help(event: Event, feature: str) -> bool:
    if isinstance(event, GroupMessageEvent):
        return group_has_feature(event.group_id, feature)

    if isinstance(event, PrivateMessageEvent):
        return is_private_feature_allowed(event.user_id, feature)

    return is_event_feature_allowed(event, feature)
