from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.shared.features import (
    groups_for_feature,
    users_for_feature,
    users_with_superusers,
)
from ironsbot.shared.messaging.push_subscription_models import (
    BUILTIN_PUSH_OPTIONS,
    PushSubscriptionOption,
    PushTargetType,
)
from ironsbot.shared.messaging.push_subscriptions import (
    build_push_subscription_menu,
    build_schedule_subscription_options,
)

from .config import get_message_config

if TYPE_CHECKING:
    from ironsbot.shared.messaging.push_subscription_store import PushUnsubscribeStore


def _eligible_target_ids_by_feature(
    target_type: PushTargetType,
    features: set[str],
) -> dict[str, set[int]]:
    if target_type == "group":
        return {
            feature: set(groups_for_feature(feature))
            for feature in features
        }

    return {
        feature: set(users_with_superusers(users_for_feature(feature)))
        for feature in features
    }


def _builtin_subscription_options(
    *,
    target_type: PushTargetType,
    target_id: int,
    store: PushUnsubscribeStore,
) -> list[PushSubscriptionOption]:
    unsubscribed = store.target_unsubscribed_keys(target_type, target_id)
    eligible = _eligible_target_ids_by_feature(
        target_type,
        {option.feature for option in BUILTIN_PUSH_OPTIONS},
    )
    options: list[PushSubscriptionOption] = []
    for option in BUILTIN_PUSH_OPTIONS:
        if target_id not in eligible.get(option.feature, set()):
            continue
        is_unsubscribed = option.key in unsubscribed
        options.append(
            PushSubscriptionOption(
                key=option.key,
                label=option.label,
                feature=option.feature,
                unsubscribed=is_unsubscribed,
            )
        )
    return options


def _schedule_subscription_options(
    *,
    target_type: PushTargetType,
    target_id: int,
    store: PushUnsubscribeStore,
) -> list[PushSubscriptionOption]:
    config = get_message_config()
    tasks = (
        config.group_schedules
        if target_type == "group"
        else config.private_schedules
    )
    features = {task.feature for task in tasks if task.enabled}
    return build_schedule_subscription_options(
        target_type=target_type,
        target_id=target_id,
        tasks=tasks,
        eligible_target_ids_for_feature=_eligible_target_ids_by_feature(
            target_type,
            features,
        ),
        store=store,
    )


def build_messaging_push_subscription_options(
    target_type: PushTargetType,
    target_id: int,
    *,
    store: PushUnsubscribeStore,
) -> list[PushSubscriptionOption]:
    from ironsbot.services.bilibili.targets import bili_push_subscription_options

    return [
        *bili_push_subscription_options(
            target_type=target_type,
            target_id=target_id,
            store=store,
        ),
        *_builtin_subscription_options(
            target_type=target_type,
            target_id=target_id,
            store=store,
        ),
        *_schedule_subscription_options(
            target_type=target_type,
            target_id=target_id,
            store=store,
        ),
    ]


def _push_subscription_menu_title(
    target_type: PushTargetType,
    *,
    read_only: bool = False,
) -> str:
    if target_type == "group" and read_only:
        return "本群推送订阅状态："
    scope = "本群" if target_type == "group" else "私聊"
    return f"请选择要切换的{scope}推送订阅："


def build_messaging_push_subscription_menu_prompt(
    target_type: PushTargetType,
    options: list[PushSubscriptionOption],
    *,
    read_only: bool = False,
) -> str:
    return build_push_subscription_menu(
        title=_push_subscription_menu_title(target_type, read_only=read_only),
        options=options,
        read_only=read_only,
    )
