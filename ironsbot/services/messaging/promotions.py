# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Protocol

from ironsbot.core.features import FIRE_MANUAL_AD_FEATURE
from ironsbot.core.messaging import append_fire_manual_ad_text


class GroupFeaturePolicy(Protocol):
    def group_has_feature(self, group_id: int, feature: str) -> bool: ...


def fire_manual_ad_enabled_for_group(
    features: GroupFeaturePolicy,
    group_id: int | None,
) -> bool:
    if group_id is None:
        return True
    return features.group_has_feature(group_id, FIRE_MANUAL_AD_FEATURE)


def append_fire_manual_ad_for_group(
    features: GroupFeaturePolicy,
    message: str,
    group_id: int | None,
) -> str:
    if not fire_manual_ad_enabled_for_group(features, group_id):
        return message
    return append_fire_manual_ad_text(message)


def split_fire_manual_ad_group_ids(
    features: GroupFeaturePolicy,
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
