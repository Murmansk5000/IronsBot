from __future__ import annotations

from typing import TYPE_CHECKING

from .push_subscription import build_messaging_push_subscription_options
from .push_time import build_push_time_options

if TYPE_CHECKING:
    from ironsbot.config.models.activity import ActivityConfig
    from ironsbot.config.models.message import MessageConfig
    from ironsbot.shared.messaging.push_subscription_models import PushTargetType
    from ironsbot.shared.messaging.push_subscription_store import (
        PushPreferencePruneResult,
        PushPreferenceTarget,
        PushTimePreferenceIdentity,
        PushUnsubscribeStore,
    )

    from .runtime_service import MessagingResources


def _valid_preferences_for_target(
    target_type: PushTargetType,
    target_id: int,
    *,
    message_config: MessageConfig,
    activity_config: ActivityConfig,
    store: PushUnsubscribeStore,
) -> tuple[set[str], set[PushTimePreferenceIdentity]]:
    subscription_keys = {
        option.key
        for option in build_messaging_push_subscription_options(
            target_type,
            target_id,
            config=message_config,
            store=store,
        )
    }
    time_preferences: set[PushTimePreferenceIdentity] = {
        (option.key, option.preference_type)
        for option in build_push_time_options(
            target_type,
            target_id,
            message_config=message_config,
            activity_config=activity_config,
            store=store,
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
            message_config=messaging.config,
            activity_config=messaging.activity,
            store=messaging.store,
        )
        valid_unsubscription_keys[target] = subscription_keys
        valid_time_preferences[target] = time_preferences

    return messaging.store.prune_invalid_preferences(
        valid_unsubscription_keys=valid_unsubscription_keys,
        valid_time_preferences=valid_time_preferences,
    )


__all__ = ["prune_stale_push_preferences"]
