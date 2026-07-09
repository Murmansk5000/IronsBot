from __future__ import annotations

from typing import Any

from ironsbot.shared.features import (
    groups_for_feature,
    users_for_feature,
    users_with_superusers,
)
from ironsbot.shared.messaging import send_broadcast_message
from ironsbot.shared.messaging.push_subscription_models import (
    CRON_TIME_PREFERENCE,
    PushTargetType,
)
from ironsbot.shared.messaging.push_subscription_store import (
    PushUnsubscribeStore,
)
from ironsbot.shared.messaging.push_subscriptions import (
    group_schedule_key,
    private_schedule_key,
)
from ironsbot.shared.promotions import (
    append_fire_manual_ad_for_group,
    append_fire_manual_ad_text,
)
from ironsbot.shared.runtime.jobs import JobRegistry

from .config import (
    GroupScheduledMessageAction,
    PrivateScheduledMessageAction,
    get_message_config,
)
from .push_time import daily_time_parts_for_push
from .runtime_service import build_schedule_job_id, build_schedule_trigger_kwargs

MESSAGE_SCHEDULE_JOB_PREFIX = "message_action_"


def _push_subscription_store() -> PushUnsubscribeStore:
    return PushUnsubscribeStore(get_message_config().push_unsubscribe.data_path)


def message_schedule_registry(scheduler: Any) -> JobRegistry:
    return JobRegistry(scheduler, prefix=MESSAGE_SCHEDULE_JOB_PREFIX)


def message_schedule_job_suffix(job_id: str) -> str:
    if not job_id.startswith(MESSAGE_SCHEDULE_JOB_PREFIX):
        return job_id
    return job_id.removeprefix(MESSAGE_SCHEDULE_JOB_PREFIX)


async def send_private_schedule(
    task: PrivateScheduledMessageAction,
    index: int = 1,
    target_user_ids: tuple[int, ...] | None = None,
) -> None:
    private_user_ids = users_with_superusers(users_for_feature(task.feature))
    if target_user_ids is None:
        override_user_ids = cron_override_target_ids(
            "private",
            private_schedule_key(index, task),
        )
        private_user_ids = [
            user_id for user_id in private_user_ids if user_id not in override_user_ids
        ]
    else:
        allowed_user_ids = set(private_user_ids)
        private_user_ids = [
            user_id for user_id in target_user_ids if user_id in allowed_user_ids
        ]

    await send_broadcast_message(
        append_fire_manual_ad_text(task.message),
        private_user_ids=private_user_ids,
        action_name=f"private scheduled message {task.id or '<unnamed>'}",
        subscription_key=private_schedule_key(index, task),
    )


async def send_group_schedule(
    task: GroupScheduledMessageAction,
    index: int = 1,
    target_group_ids: tuple[int, ...] | None = None,
) -> None:
    group_ids = groups_for_feature(task.feature)
    if target_group_ids is None:
        override_group_ids = cron_override_target_ids(
            "group",
            group_schedule_key(index, task),
        )
        group_ids = [
            group_id for group_id in group_ids if group_id not in override_group_ids
        ]
    else:
        allowed_group_ids = set(group_ids)
        group_ids = [
            group_id for group_id in target_group_ids if group_id in allowed_group_ids
        ]

    await send_broadcast_message(
        task.message,
        group_ids=group_ids,
        group_at_user_ids=task.at_user_ids,
        action_name=f"group scheduled message {task.id or '<unnamed>'}",
        message_limiter=append_fire_manual_ad_for_group,
        subscription_key=group_schedule_key(index, task),
    )


def cron_override_target_ids(
    target_type: PushTargetType,
    subscription_key: str,
) -> set[int]:
    store = _push_subscription_store()
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
    task: PrivateScheduledMessageAction | GroupScheduledMessageAction,
    value: str,
) -> dict[str, Any]:
    hour, minute = daily_time_parts_for_push(value)
    trigger_kwargs = schedule_trigger_kwargs(task)
    trigger_kwargs["hour"] = hour
    trigger_kwargs["minute"] = minute
    return trigger_kwargs


def schedule_trigger_kwargs(
    task: PrivateScheduledMessageAction | GroupScheduledMessageAction,
) -> dict[str, Any]:
    return dict(build_schedule_trigger_kwargs(task))


def _register_private_schedule_overrides(
    registry: JobRegistry,
    index: int,
    task: PrivateScheduledMessageAction,
) -> None:
    key = private_schedule_key(index, task)
    eligible_user_ids = set(users_with_superusers(users_for_feature(task.feature)))
    store = _push_subscription_store()
    for preference in store.all_time_preferences(
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
            send_private_schedule,
            "cron",
            kwargs={
                "task": task,
                "index": index,
                "target_user_ids": (preference.target_id,),
            },
            job_id=message_schedule_job_suffix(job_id),
            **trigger_kwargs,
        )


def _register_group_schedule_overrides(
    registry: JobRegistry,
    index: int,
    task: GroupScheduledMessageAction,
) -> None:
    key = group_schedule_key(index, task)
    eligible_group_ids = set(groups_for_feature(task.feature))
    store = _push_subscription_store()
    for preference in store.all_time_preferences(
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
            send_group_schedule,
            "cron",
            kwargs={
                "task": task,
                "index": index,
                "target_group_ids": (preference.target_id,),
            },
            job_id=message_schedule_job_suffix(job_id),
            **trigger_kwargs,
        )


def _register_private_schedule(
    registry: JobRegistry,
    index: int,
    task: PrivateScheduledMessageAction,
) -> None:
    if not task.enabled:
        return

    job_id = build_schedule_job_id("private_schedule", index, task.id)
    registry.add(
        send_private_schedule,
        "cron",
        kwargs={"task": task, "index": index},
        job_id=message_schedule_job_suffix(job_id),
        **schedule_trigger_kwargs(task),
    )
    _register_private_schedule_overrides(registry, index, task)


def _register_group_schedule(
    registry: JobRegistry,
    index: int,
    task: GroupScheduledMessageAction,
) -> None:
    if not task.enabled:
        return

    job_id = build_schedule_job_id("group_schedule", index, task.id)
    registry.add(
        send_group_schedule,
        "cron",
        kwargs={"task": task, "index": index},
        job_id=message_schedule_job_suffix(job_id),
        **schedule_trigger_kwargs(task),
    )
    _register_group_schedule_overrides(registry, index, task)


async def register_message_schedules(scheduler: Any) -> None:
    config = get_message_config()

    def register_jobs(registry: JobRegistry) -> None:
        for index, task in enumerate(config.private_schedules, start=1):
            _register_private_schedule(registry, index, task)

        for index, task in enumerate(config.group_schedules, start=1):
            _register_group_schedule(registry, index, task)

    message_schedule_registry(scheduler).replace_all(register_jobs)


def clear_message_schedule_jobs(scheduler: Any) -> None:
    message_schedule_registry(scheduler).remove_by_prefix()
