from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.shared.messaging.push_subscription_models import (
    BUILTIN_PUSH_OPTIONS,
    PushSubscriptionOption,
    PushTargetType,
)
from ironsbot.shared.messaging.push_subscriptions import (
    build_push_subscription_menu,
    build_schedule_subscription_options,
)

if TYPE_CHECKING:
    from ironsbot.plugins.messaging.runtime_service import MessagingResources


def _builtin_subscription_options(
    *,
    target_type: PushTargetType,
    target_id: int,
    messaging: MessagingResources,
) -> list[PushSubscriptionOption]:
    unsubscribed = messaging.store.target_unsubscribed_keys(target_type, target_id)
    eligible = messaging.eligible_target_ids(
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
    messaging: MessagingResources,
) -> list[PushSubscriptionOption]:
    tasks = (
        messaging.config.group_schedules
        if target_type == "group"
        else messaging.config.private_schedules
    )
    features = {task.feature for task in tasks if task.enabled}
    return build_schedule_subscription_options(
        target_type=target_type,
        target_id=target_id,
        tasks=tasks,
        eligible_target_ids_for_feature=messaging.eligible_target_ids(
            target_type,
            features,
        ),
        store=messaging.store,
    )


def build_messaging_push_subscription_options(
    target_type: PushTargetType,
    target_id: int,
    *,
    messaging: MessagingResources,
) -> list[PushSubscriptionOption]:
    return [
        *messaging.extra_push_options(target_type, target_id),
        *_builtin_subscription_options(
            target_type=target_type,
            target_id=target_id,
            messaging=messaging,
        ),
        *_schedule_subscription_options(
            target_type=target_type,
            target_id=target_id,
            messaging=messaging,
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
