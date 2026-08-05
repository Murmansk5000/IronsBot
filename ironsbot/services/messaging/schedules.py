# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from ironsbot.core.platform import (
    ConversationKind,
    ConversationRef,
    private_conversation_for_actor,
)
from ironsbot.services.messaging.scheduled_delivery import (
    ScheduledMessageDelivery,
)
from ironsbot.services.messaging.subscription_options import schedule_key
from ironsbot.services.messaging.subscriptions import (
    CRON_TIME_PREFERENCE,
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
    target_conversations: tuple[ConversationRef, ...] | None = None,
    *,
    messaging: MessagingService,
) -> None:
    eligible = tuple(
        private_conversation_for_actor(actor)
        for actor in messaging._features.actors_with_superusers(task.feature)
    )
    if target_conversations is None:
        overrides = cron_override_conversations(
            messaging._store,
            "private",
            schedule_key(index, task),
        )
        recipients = tuple(
            conversation
            for conversation in eligible
            if conversation not in overrides
        )
    else:
        allowed = set(eligible)
        recipients = tuple(
            conversation
            for conversation in target_conversations
            if conversation in allowed
        )

    await messaging._schedule_sender.send(
        ScheduledMessageDelivery(
            message=task.message,
            private_conversations=recipients,
            group_conversations=(),
            group_mentions=(),
            action_name=f"private scheduled message {task.id or '<unnamed>'}",
            subscription_key=schedule_key(index, task),
        )
    )


async def send_group_schedule(
    task: MessageScheduledAction,
    index: int = 1,
    target_conversations: tuple[ConversationRef, ...] | None = None,
    *,
    messaging: MessagingService,
) -> None:
    eligible = tuple(messaging._features.conversations_for_feature(task.feature))
    if target_conversations is None:
        overrides = cron_override_conversations(
            messaging._store,
            "group",
            schedule_key(index, task),
        )
        recipients = tuple(
            conversation
            for conversation in eligible
            if conversation not in overrides
        )
    else:
        allowed = set(eligible)
        recipients = tuple(
            conversation
            for conversation in target_conversations
            if conversation in allowed
        )

    await messaging._schedule_sender.send(
        ScheduledMessageDelivery(
            message=task.message,
            private_conversations=(),
            group_conversations=recipients,
            group_mentions=tuple(
                messaging._features.actor_refs(task.at_user_ids)
            ),
            action_name=f"group scheduled message {task.id or '<unnamed>'}",
            subscription_key=schedule_key(index, task),
        )
    )


async def send_schedule(
    task: MessageScheduledAction,
    index: int = 1,
    *,
    messaging: MessagingService,
) -> None:
    await send_private_schedule(task, index, messaging=messaging)
    await send_group_schedule(task, index, messaging=messaging)


def cron_override_conversations(
    store: PushSubscriptionRepository,
    conversation_kind: ConversationKind,
    subscription_key: str,
) -> set[ConversationRef]:
    return {
        preference.conversation
        for preference in store.all_time_preferences(
            conversation_kind=conversation_kind,
            subscription_key=subscription_key,
            preference_type=CRON_TIME_PREFERENCE,
        )
    }


def schedule_override_job_id(
    prefix: str,
    index: int,
    task_id: str,
    conversation: ConversationRef,
) -> str:
    target_key = "_".join(
        (conversation.platform.value, conversation.kind, conversation.id)
    )
    return build_schedule_job_id(prefix, index, f"{task_id}_override_{target_key}")


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
    eligible = {
        private_conversation_for_actor(actor)
        for actor in messaging._features.actors_with_superusers(task.feature)
    }
    for preference in messaging._store.all_time_preferences(
        conversation_kind="private",
        subscription_key=key,
        preference_type=CRON_TIME_PREFERENCE,
    ):
        if preference.conversation not in eligible:
            continue
        try:
            trigger_kwargs = schedule_override_trigger_kwargs(task, preference.value)
        except ValueError:
            continue
        registry.add(
            partial(send_private_schedule, messaging=messaging),
            "cron",
            kwargs={
                "task": task,
                "index": index,
                "target_conversations": (preference.conversation,),
            },
            job_id=schedule_override_job_id(
                "private_schedule",
                index,
                key,
                preference.conversation,
            ),
            **trigger_kwargs,
        )


def _register_group_schedule_overrides(
    registry: JobRegistry,
    index: int,
    task: MessageScheduledAction,
    messaging: MessagingService,
) -> None:
    key = schedule_key(index, task)
    eligible = set(messaging._features.conversations_for_feature(task.feature))
    for preference in messaging._store.all_time_preferences(
        conversation_kind="group",
        subscription_key=key,
        preference_type=CRON_TIME_PREFERENCE,
    ):
        if preference.conversation not in eligible:
            continue
        try:
            trigger_kwargs = schedule_override_trigger_kwargs(task, preference.value)
        except ValueError:
            continue
        registry.add(
            partial(send_group_schedule, messaging=messaging),
            "cron",
            kwargs={
                "task": task,
                "index": index,
                "target_conversations": (preference.conversation,),
            },
            job_id=schedule_override_job_id(
                "group_schedule",
                index,
                key,
                preference.conversation,
            ),
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

    registry.add(
        partial(send_schedule, messaging=messaging),
        "cron",
        kwargs={"task": task, "index": index},
        job_id=build_schedule_job_id("schedule", index, task.id),
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
