# SPDX-License-Identifier: MIT
"""Shared help-visibility predicates for the plugin registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from ironsbot.runtime.feature_policy import event_is_feature_visible_in_help

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.core.features import FeatureService


def always_help_visible(_event: Event) -> bool:
    return True


def feature_help_visible(
    event: Event,
    *,
    features: FeatureService,
    feature: str,
    enabled: bool = True,
    group_only: bool = False,
) -> bool:
    return (
        enabled
        and (not group_only or isinstance(event, GroupMessageEvent))
        and event_is_feature_visible_in_help(features, event, feature)
    )


def superuser_help_visible(
    event: Event,
    *,
    features: FeatureService,
) -> bool:
    if isinstance(event, GroupMessageEvent):
        return False
    user_id = getattr(event, "user_id", None)
    return user_id is not None and features.is_superuser(int(user_id))
