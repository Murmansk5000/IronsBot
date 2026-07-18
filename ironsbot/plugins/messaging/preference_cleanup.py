from __future__ import annotations

from typing import TYPE_CHECKING

from .push_subscription import build_messaging_push_subscription_options
from .push_time import build_push_time_options

if TYPE_CHECKING:
    from ironsbot.shared.messaging.push_subscription_models import PushTargetType
    from ironsbot.shared.messaging.push_subscription_store import (
        PushPreferencePruneResult,
        PushPreferenceTarget,
        PushTimePreferenceIdentity,
    )

    from .runtime_service import MessagingResources


def _valid_preferences_for_target(
    target_type: PushTargetType,
    target_id: int,
    *,
    messaging: MessagingResources,
) -> tuple[set[str], set[PushTimePreferenceIdentity]]:
    subscription_keys = {
        option.key
        for option in build_messaging_push_subscription_options(
            target_type,
            target_id,
            messaging=messaging,
        )
    }
    time_preferences: set[PushTimePreferenceIdentity] = {
        (option.key, option.preference_type)
        for option in build_push_time_options(
            target_type,
            target_id,
            messaging=messaging,
        )
    }
    return subscription_keys, time_preferences


def prune_stale_push_preferences(
    messaging: MessagingResources,
) -> PushPreferencePruneResult:
    valid_unsubscription_keys: dict[PushPreferenceTarget, set[str]] = {}
    valid_time_preferences: dict[
        PushPreferenceTarget,
        set[PushTimePreferenceIdentity],
    ] = {}

    for target in messaging.store.preference_targets():
        target_type, target_id = target
        subscription_keys, time_preferences = _valid_preferences_for_target(
            target_type,
            target_id,
            messaging=messaging,
        )
        valid_unsubscription_keys[target] = subscription_keys
        valid_time_preferences[target] = time_preferences

    return messaging.store.prune_invalid_preferences(
        valid_unsubscription_keys=valid_unsubscription_keys,
        valid_time_preferences=valid_time_preferences,
    )
