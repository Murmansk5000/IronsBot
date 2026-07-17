from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.shared.messaging.push_subscription_store import (
    PushPreferencePruneResult,
    PushUnsubscribeStore,
)

from .config import get_message_config
from .push_subscription import build_messaging_push_subscription_options
from .push_time import build_push_time_options

if TYPE_CHECKING:
    from ironsbot.shared.messaging.push_subscription_models import PushTargetType
    from ironsbot.shared.messaging.push_subscription_store import (
        PushPreferenceTarget,
        PushTimePreferenceIdentity,
    )


def _valid_preferences_for_target(
    target_type: PushTargetType,
    target_id: int,
    *,
    store: PushUnsubscribeStore,
) -> tuple[set[str], set[PushTimePreferenceIdentity]]:
    subscription_keys = {
        option.key
        for option in build_messaging_push_subscription_options(
            target_type,
            target_id,
            store=store,
        )
    }
    time_preferences: set[PushTimePreferenceIdentity] = {
        (option.key, option.preference_type)
        for option in build_push_time_options(
            target_type,
            target_id,
            store=store,
        )
    }
    return subscription_keys, time_preferences


def prune_stale_push_preferences() -> PushPreferencePruneResult:
    store = PushUnsubscribeStore(get_message_config().push_unsubscribe.data_path)
    valid_unsubscription_keys: dict[PushPreferenceTarget, set[str]] = {}
    valid_time_preferences: dict[
        PushPreferenceTarget,
        set[PushTimePreferenceIdentity],
    ] = {}

    for target in store.preference_targets():
        target_type, target_id = target
        subscription_keys, time_preferences = _valid_preferences_for_target(
            target_type,
            target_id,
            store=store,
        )
        valid_unsubscription_keys[target] = subscription_keys
        valid_time_preferences[target] = time_preferences

    return store.prune_invalid_preferences(
        valid_unsubscription_keys=valid_unsubscription_keys,
        valid_time_preferences=valid_time_preferences,
    )


__all__ = ["prune_stale_push_preferences"]
