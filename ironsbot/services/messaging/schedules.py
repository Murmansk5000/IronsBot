# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from ironsbot.core.messaging import append_fire_manual_ad_text
from ironsbot.services.messaging.promotions import append_fire_manual_ad_for_group
from ironsbot.services.messaging.subscription_options import (
    schedule_key,
)
from ironsbot.services.messaging.subscriptions import (
    CRON_TIME_PREFERENCE,
    PushTargetType,
)
from ironsbot.services.operations.scheduler import JobRegistry

from .push_time import daily_time_parts_for_push
from .service import build_schedule_job_id, build_schedule_trigger_kwargs

if TYPE_CHECKING:
    from ironsbot.config.models.messaging import MessageScheduledAction
    from ironsbot.services.messaging.subscriptions import (
        PushSubscriptionRepository,
    )

    from .service import MessagingService

MESSAGE_SCHEDULE_JOB_PREFIX = "message_action_"


async def send_private_schedule(
    task: MessageScheduledAction,
    index: int = 1,
    target_user_ids: tuple[int, ...] | None = None,
    *,
    messaging: MessagingService,
) -> None:
    private_user_ids = messaging._features.users_with_superusers(
        messaging._features.users_for_feature(task.feature)
    )
    if target_user_ids is None:
        override_user_ids = cron_override_target_ids(
            messaging._store,
            "private",
            schedule_key(index, task),
        )
        private_user_ids = [
            user_id for user_id in private_user_ids if user_id not in override_user_ids
        ]
    else:
        allowed_user_ids = set(private_user_ids)
        private_user_ids = [
            user_id for user_id in target_user_ids if user_id in allowed_user_ids
        ]

    await messaging._delivery.broadcast(
        append_fire_manual_ad_text(task.message),
        private_user_ids=private_user_ids,
        action_name=f"private scheduled message {task.id or '<unnamed>'}",
        subscription_key=schedule_key(index, task),
    )


async def send_group_schedule(
    task: MessageScheduledAction,
    index: int = 1,
    target_group_ids: tuple[int, ...] | None = None,
    *,
    messaging: MessagingService,
) -> None:
    group_ids = messaging._features.groups_for_feature(task.feature)
    if target_group_ids is None:
        override_group_ids = cron_override_target_ids(
            messaging._store,
            "group",
            schedule_key(index, task),
        )
        group_ids = [
            group_id for group_id in group_ids if group_id not in override_group_ids
        ]
    else:
        allowed_group_ids = set(group_ids)
        group_ids = [
            group_id for group_id in target_group_ids if group_id in allowed_group_ids
        ]

    await messaging._delivery.broadcast(
        task.message,
        group_ids=group_ids,
        group_at_user_ids=task.at_user_ids,
        action_name=f"group scheduled message {task.id or '<unnamed>'}",
        message_limiter=partial(
            append_fire_manual_ad_for_group,
            messaging._features,
        ),
        subscription_key=schedule_key(index, task),
    )


async def send_schedule(
    task: MessageScheduledAction,
    index: int = 1,
    *,
    messaging: MessagingService,
) -> None:
    await send_private_schedule(task, index, messaging=messaging)
    await send_group_schedule(task, index, messaging=messaging)


def cron_override_target_ids(
    store: PushSubscriptionRepository,
    target_type: PushTargetType,
    subscription_key: str,
) -> set[int]:
    return {
        preference.target_id
        for preference in store.all_time_preferences(
            target_type=target_type,
            subscription_key=subscription_key,
            preference_type=CRON_TIME_PREFERENCE,
        )
    }


def schedule_override_job_id(
    prefix: str,
    index: int,
    task_id: str,
    target_id: int,
) -> str:
    return build_schedule_job_id(prefix, index, f"{task_id}_override_{target_id}")


def schedule_override_trigger_kwargs(
    task: MessageScheduledAction,
    value: str,
) -> dict[str, Any]:
    hour, minute = daily_time_parts_for_push(value)
    trigger_kwargs = build_schedule_trigger_kwargs(task)
    trigger_kwargs["hour"] = hour
    trigger_kwargs["minute"] = minute
    return trigger_kwargs


def _register_private_schedule_overrides(
    registry: JobRegistry,
    index: int,
    task: MessageScheduledAction,
    messaging: MessagingService,
) -> None:
    key = schedule_key(index, task)
    eligible_user_ids = set(
        messaging._features.users_with_superusers(
            messaging._features.users_for_feature(task.feature)
        )
    )
    for preference in messaging._store.all_time_preferences(
        target_type="private",
        subscription_key=key,
        preference_type=CRON_TIME_PREFERENCE,
    ):
        if preference.target_id not in eligible_user_ids:
            continue
        try:
            trigger_kwargs = schedule_override_trigger_kwargs(task, preference.value)
        except ValueError:
            continue
        job_id = schedule_override_job_id(
            "private_schedule",
            index,
            key,
            preference.target_id,
        )
        registry.add(
            partial(send_private_schedule, messaging=messaging),
            "cron",
            kwargs={
                "task": task,
                "index": index,
                "target_user_ids": (preference.target_id,),
            },
            job_id=job_id,
            **trigger_kwargs,
        )


def _register_group_schedule_overrides(
    registry: JobRegistry,
    index: int,
    task: MessageScheduledAction,
    messaging: MessagingService,
) -> None:
    key = schedule_key(index, task)
    eligible_group_ids = set(
        messaging._features.groups_for_feature(task.feature)
    )
    for preference in messaging._store.all_time_preferences(
        target_type="group",
        subscription_key=key,
        preference_type=CRON_TIME_PREFERENCE,
    ):
        if preference.target_id not in eligible_group_ids:
            continue
        try:
            trigger_kwargs = schedule_override_trigger_kwargs(task, preference.value)
        except ValueError:
            continue
        job_id = schedule_override_job_id(
            "group_schedule",
            index,
            key,
            preference.target_id,
        )
        registry.add(
            partial(send_group_schedule, messaging=messaging),
            "cron",
            kwargs={
                "task": task,
                "index": index,
                "target_group_ids": (preference.target_id,),
            },
            job_id=job_id,
            **trigger_kwargs,
        )


def _register_schedule(
    registry: JobRegistry,
    index: int,
    task: MessageScheduledAction,
    messaging: MessagingService,
) -> None:
    if not task.enabled:
        return

    job_id = build_schedule_job_id("schedule", index, task.id)
    registry.add(
        partial(send_schedule, messaging=messaging),
        "cron",
        kwargs={"task": task, "index": index},
        job_id=job_id,
        **build_schedule_trigger_kwargs(task),
    )
    _register_private_schedule_overrides(registry, index, task, messaging)
    _register_group_schedule_overrides(registry, index, task, messaging)


async def register_message_schedules(
    scheduler: Any,
    messaging: MessagingService,
) -> None:
    def register_jobs(registry: JobRegistry) -> None:
        for index, task in enumerate(messaging._config.schedules, start=1):
            _register_schedule(registry, index, task, messaging)

    JobRegistry(
        scheduler,
        prefix=MESSAGE_SCHEDULE_JOB_PREFIX,
    ).replace_all(register_jobs)
