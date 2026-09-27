# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ironsbot.core.platform import ConversationRef
from ironsbot.core.selection import (
    TOGGLE_SELECTION_FOOTER,
    SelectionMenuItem,
    format_selection_menu,
)
from ironsbot.services.messaging.subscriptions import (
    CRON_TIME_PREFERENCE,
    PushSubscriptionOption,
    PushSubscriptionRepository,
    ScheduledPushTask,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.core.platform import ConversationRef

READONLY_SELECTION_FOOTER = "✅ 已订阅 · ❌ 已退订，普通群员仅可查看 · 输入 0 退出"


def push_subscription_command_texts(
    commands: Sequence[str], restore_commands: Sequence[str]
) -> tuple[str, ...]:
    return tuple(dict.fromkeys(("推送管理", *commands, *restore_commands)))


class ScheduledPushKeyError(ValueError):
    @classmethod
    def missing_id(cls, index: int) -> ScheduledPushKeyError:
        return cls(f"scheduled task {index} requires a stable id")


def schedule_key(index: int, task: ScheduledPushTask) -> str:
    raw_id = task.id.strip()
    if not raw_id:
        raise ScheduledPushKeyError.missing_id(index)
    return raw_id


def timed_subscription_label(
    name: str,
    time: str,
    *,
    day_of_week: str | None = None,
    timezone: str | None = None,
) -> str:
    schedule = f"{day_of_week or '每日'} {time}"
    if timezone and timezone != "Asia/Shanghai":
        schedule = f"{schedule}，{timezone}"
    return f"{name}（{schedule}）"


def schedule_label(
    index: int, task: ScheduledPushTask, *, effective_time: str | None = None
) -> str:
    name = _schedule_display_name(index, task)
    return timed_subscription_label(
        name,
        effective_time or task.time,
        day_of_week=task.day_of_week,
    )


def _schedule_display_name(index: int, task: ScheduledPushTask) -> str:
    configured_name = getattr(task, "name", "").strip()
    if configured_name:
        return configured_name

    message_name = next(
        (
            name
            for message in task.messages
            if (name := _schedule_display_name_from_message(message))
        ),
        "",
    )
    if message_name:
        return message_name

    return _schedule_display_name_from_feature(index, task)


def _schedule_display_name_from_message(message: str) -> str:
    for raw_line in message.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.split(r"https?://", line, maxsplit=1)[0]
        line = line.rstrip("：:，,。；; \t")
        if line:
            return line[:24]
    return ""


def _schedule_display_name_from_feature(
    index: int,
    task: ScheduledPushTask,
) -> str:
    feature_names = {
        "text_push": "定时文本推送",
        "web_activity_push": "游戏外活动推送",
    }
    if task.feature in feature_names:
        return feature_names[task.feature]
    return task.id.strip() or f"scheduled message {index}"


def build_schedule_subscription_options(
    *,
    conversation: ConversationRef,
    tasks: Sequence[ScheduledPushTask],
    eligible_conversations_for_feature: dict[str, set[ConversationRef]],
    store: PushSubscriptionRepository,
) -> list[PushSubscriptionOption]:
    unsubscribed = store.unsubscribed_keys(conversation)
    options: list[PushSubscriptionOption] = []

    for index, task in enumerate(tasks, start=1):
        if not task.enabled:
            continue
        if conversation not in eligible_conversations_for_feature.get(
            task.feature,
            set(),
        ):
            continue

        key = schedule_key(index, task)
        is_unsubscribed = key in unsubscribed

        effective_time = store.get_time_preference(
            conversation,
            key,
            CRON_TIME_PREFERENCE,
        )
        label = schedule_label(index, task, effective_time=effective_time)
        options.append(
            PushSubscriptionOption(
                key=key,
                label=label,
                feature=task.feature,
                unsubscribed=is_unsubscribed,
            )
        )

    return options


def build_push_subscription_menu(
    *,
    title: str,
    options: Sequence[PushSubscriptionOption],
    read_only: bool = False,
) -> str:
    return format_selection_menu(
        title=title,
        items=tuple(
            SelectionMenuItem(
                label=option.label,
                prefix="❌" if option.unsubscribed else "✅",
            )
            for option in options
        ),
        footer=READONLY_SELECTION_FOOTER if read_only else TOGGLE_SELECTION_FOOTER,
    )
