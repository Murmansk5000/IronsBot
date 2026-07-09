# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.shared.messaging.push_subscription_models import (
    PushSubscriptionOption,
    PushTargetType,
    ScheduledPushTask,
)
from ironsbot.shared.selection_menu import (
    TOGGLE_SELECTION_FOOTER,
    SelectionMenuItem,
    format_selection_menu,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.config.models.message import PushUnsubscribeConfig
    from ironsbot.shared.messaging.push_subscription_store import PushUnsubscribeStore

READONLY_SELECTION_FOOTER = "✅ 已订阅 · ❌ 已退订，普通群员仅可查看 · 输入 0 退出"


def private_schedule_key(index: int, task: ScheduledPushTask) -> str:
    return schedule_key("private_schedule", index, task)


def group_schedule_key(index: int, task: ScheduledPushTask) -> str:
    return schedule_key("group_schedule", index, task)


def schedule_key(prefix: str, index: int, task: ScheduledPushTask) -> str:
    raw_id = task.id.strip()
    if raw_id:
        return raw_id
    return build_subscription_job_id(prefix, index, "")


def build_subscription_job_id(prefix: str, index: int, raw_id: str) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw_id or f"task_{index}")
    safe_id = safe_id.strip("_") or str(index)
    return f"message_action_{prefix}_{safe_id}"


def private_schedule_label(index: int, task: ScheduledPushTask) -> str:
    return schedule_label("私聊推送", index, task)


def group_schedule_label(index: int, task: ScheduledPushTask) -> str:
    return schedule_label("群推送", index, task)


def schedule_label(scope: str, index: int, task: ScheduledPushTask) -> str:
    name = _schedule_display_name(scope, index, task)
    time_label = f"{task.hour:02d}:{task.minute:02d}"
    if task.day_of_week:
        time_label = f"{task.day_of_week} {time_label}"
    return f"{name}（{time_label}）"


def _schedule_display_name(scope: str, index: int, task: ScheduledPushTask) -> str:
    configured_name = getattr(task, "name", "").strip()
    if configured_name:
        return configured_name

    message_name = _schedule_display_name_from_message(task.message)
    if message_name:
        return message_name

    return _schedule_display_name_from_feature(scope, index, task)


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
    scope: str,
    index: int,
    task: ScheduledPushTask,
) -> str:
    feature_names = {
        "text_push": "定时文本推送",
        "web_activity_push": "游戏外活动推送",
    }
    if task.feature in feature_names:
        return feature_names[task.feature]
    return task.id.strip() or f"{scope}{index}"


def append_push_unsubscribe_hint(
    message: str | Message,
    config: PushUnsubscribeConfig,
    *,
    target_type: PushTargetType,
) -> str | Message:
    hint = (
        config.group_hint.strip()
        if target_type == "group"
        else config.hint.strip()
    )
    if not hint:
        return message.rstrip() if isinstance(message, str) else message

    if isinstance(message, Message):
        if hint in str(message):
            return message
        message += MessageSegment.text(f"\n\n{hint}")
        return message

    text = message.rstrip()
    if hint in text:
        return text
    if not text:
        return hint
    return f"{text}\n\n{hint}"


def build_schedule_subscription_options(
    *,
    target_type: PushTargetType,
    target_id: int,
    tasks: Sequence[ScheduledPushTask],
    eligible_target_ids_for_feature: dict[str, set[int]],
    store: PushUnsubscribeStore,
) -> list[PushSubscriptionOption]:
    unsubscribed = store.target_unsubscribed_keys(target_type, target_id)
    options: list[PushSubscriptionOption] = []

    for index, task in enumerate(tasks, start=1):
        if not task.enabled:
            continue
        if target_id not in eligible_target_ids_for_feature.get(task.feature, set()):
            continue

        key = (
            private_schedule_key(index, task)
            if target_type == "private"
            else group_schedule_key(index, task)
        )
        is_unsubscribed = key in unsubscribed

        label = (
            private_schedule_label(index, task)
            if target_type == "private"
            else group_schedule_label(index, task)
        )
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

__all__ = [
    "append_push_unsubscribe_hint",
    "build_push_subscription_menu",
    "build_schedule_subscription_options",
    "group_schedule_key",
    "private_schedule_key",
]
