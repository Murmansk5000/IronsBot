# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ironsbot.core.features import FIRE_MANUAL_AD_FEATURE

if TYPE_CHECKING:
    from ironsbot.core.messaging import MessageTarget


class TargetFeaturePolicy(Protocol):
    def group_has_feature(self, group_id: int, feature: str) -> bool: ...

    def users_for_feature(self, feature: str) -> list[int]: ...


def fire_manual_ad_enabled_for_target(
    features: TargetFeaturePolicy,
    target: MessageTarget,
) -> bool:
    if target.target_type == "group":
        return features.group_has_feature(target.target_id, FIRE_MANUAL_AD_FEATURE)
    return target.target_id in features.users_for_feature(FIRE_MANUAL_AD_FEATURE)
