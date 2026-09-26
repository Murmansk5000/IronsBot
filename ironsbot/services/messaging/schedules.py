# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from ironsbot.core.platform import (
    ConversationKind,
    ConversationRef,
    private_conversation_for_actor,
)
from ironsbot.core.schedule_rendering import ScheduledRenderRequest
from ironsbot.core.time import TZ_CN
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
logger = logging.getLogger(__name__)


def render_schedule_messages(
    task: MessageScheduledAction, *, messaging: MessagingService
) -> tuple[str, ...]:
    if not task.renderer:
        return tuple(task.messages)
    request = ScheduledRenderRequest(
        today=datetime.now(TZ_CN).date(),
        messages=tuple(task.messages),
        parameters=task.renderer_parameters,
    )
    try:
        rendered = messaging.schedule_renderers.render(task.renderer, request)
    except (KeyError, ValueError) as error:
        logger.warning(
            "scheduled message rendering failed: task=%s renderer=%s error=%s",
            task.id,
            task.renderer,
            error,
        )
        return ()
    if rendered is None:
        logger.warning(
            "scheduled message renderer unavailable: task=%s renderer=%s",
            task.id,
            task.renderer,
        )
        return ()
    return rendered


async def send_private_schedule(
    task: MessageScheduledAction,
    index: int = 1,
    target_conversations: tuple[ConversationRef, ...] | None = None,
    *,
    messaging: MessagingService,
    messages: tuple[str, ...] | None = None,
) -> None:
    if task.target_groups:
        return
    if messages is None:
        messages = render_schedule_messages(task, messaging=messaging)
    if not messages:
        return
    eligible = tuple(
        private_conversation_for_actor(actor)
        for actor in messaging._features.private_actors_for_feature(task.feature)
    )
    if target_conversations is None:
        overrides = cron_override_conversations(
            messaging._store,
            "private",
            schedule_key(index, task),
        )
        recipients = tuple(
            conversation for conversation in eligible if conversation not in overrides
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
            messages=messages,
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
    messages: tuple[str, ...] | None = None,
) -> None:
    if messages is None:
        messages = render_schedule_messages(task, messaging=messaging)
    if not messages:
        return
    eligible = eligible_group_schedule_conversations(task, index, messaging=messaging)
    if task.target_groups and not eligible:
        return
    if target_conversations is None:
        overrides = cron_override_conversations(
            messaging._store,
            "group",
            schedule_key(index, task),
        )
        recipients = tuple(
            conversation for conversation in eligible if conversation not in overrides
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
            messages=messages,
            private_conversations=(),
            group_conversations=recipients,
            group_mentions=messaging.schedule_mentions(index),
            action_name=f"group scheduled message {task.id or '<unnamed>'}",
            subscription_key=schedule_key(index, task),
            unresolved_mentions_as_text=task.unresolved_mentions == "text",
            mention_fallback_name=task.mention_fallback_name,
        )
    )


def eligible_group_schedule_conversations(
    task: MessageScheduledAction, index: int, *, messaging: MessagingService
) -> tuple[ConversationRef, ...]:
    eligible = tuple(messaging._features.conversations_for_feature(task.feature))
    if task.target_groups:
        principals = messaging._features.principals
        targets = messaging._schedule_targets.groups_for(index)
        if not targets:
            logger.warning(
                "scheduled message target groups unavailable: task=%s", task.id
            )
            return ()
        if principals is None:
            eligible = tuple(item for item in eligible if item in targets)
        else:
            allowed = {principals.conversation_principal(target) for target in targets}
            eligible = tuple(
                conversation
                for conversation in eligible
                if principals.conversation_principal(conversation) in allowed
            )
    return eligible


async def send_schedule(
    task: MessageScheduledAction,
    index: int = 1,
    *,
    messaging: MessagingService,
) -> None:
    messages = render_schedule_messages(task, messaging=messaging)
    if not messages:
        return
    await send_private_schedule(task, index, messaging=messaging, messages=messages)
    await send_group_schedule(task, index, messaging=messaging, messages=messages)


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
    hour, minute, second = daily_time_parts_for_push(value)
    trigger_kwargs = build_schedule_trigger_kwargs(task)
    trigger_kwargs["hour"] = hour
    trigger_kwargs["minute"] = minute
    trigger_kwargs["second"] = second
    return trigger_kwargs


def _register_private_schedule_overrides(
    registry: JobRegistry,
    index: int,
    task: MessageScheduledAction,
    messaging: MessagingService,
) -> None:
    if task.target_groups:
        return
    key = schedule_key(index, task)
    eligible = {
        private_conversation_for_actor(actor)
        for actor in messaging._features.private_actors_for_feature(task.feature)
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
    eligible = set(
        eligible_group_schedule_conversations(task, index, messaging=messaging)
    )
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
