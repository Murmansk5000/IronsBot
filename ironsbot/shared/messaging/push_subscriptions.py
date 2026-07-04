# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from nonebot.adapters.onebot.v11 import Message, MessageSegment

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ironsbot.config.models.message import PushUnsubscribeConfig

PushTargetType = Literal["private", "group"]


class ScheduledPushTask(Protocol):
    id: str
    name: str
    enabled: bool
    feature: str
    message: str
    hour: int
    minute: int
    day_of_week: str | None


@dataclass(frozen=True, slots=True)
class PushSubscriptionOption:
    key: str
    label: str
    feature: str


BUILTIN_PUSH_OPTIONS: tuple[PushSubscriptionOption, ...] = (
    PushSubscriptionOption("bili_push", "B站动态推送", "bili_push"),
    PushSubscriptionOption("seer_activity_push", "活动结束提醒", "seer_activity_push"),
    PushSubscriptionOption("server_status_push", "开服推送", "server_status_push"),
    PushSubscriptionOption("admin_notice", "管理通知", "admin_notice"),
)


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


class PushUnsubscribeStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def target_unsubscribed_keys(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> set[str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT subscription_key FROM push_unsubscriptions "
                "WHERE target_type = ? AND target_id = ?",
                (target_type, int(target_id)),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def is_target_unsubscribed(
        self,
        target_type: PushTargetType,
        target_id: int,
        subscription_key: str,
    ) -> bool:
        with self._connect() as con:
            row = con.execute(
                "SELECT 1 FROM push_unsubscriptions "
                "WHERE target_type = ? AND target_id = ? AND subscription_key = ?",
                (target_type, int(target_id), subscription_key),
            ).fetchone()
        return row is not None

    def unsubscribe_target(
        self,
        target_type: PushTargetType,
        target_id: int,
        subscription_key: str,
        feature: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO push_unsubscriptions "
                "(target_type, target_id, subscription_key, feature, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (target_type, int(target_id), subscription_key, feature, now),
            )
            con.commit()

    def restore_target(
        self,
        target_type: PushTargetType,
        target_id: int,
        subscription_key: str,
    ) -> None:
        with self._connect() as con:
            con.execute(
                "DELETE FROM push_unsubscriptions "
                "WHERE target_type = ? AND target_id = ? AND subscription_key = ?",
                (target_type, int(target_id), subscription_key),
            )
            con.commit()

    def filter_subscribed_target_ids(
        self,
        target_type: PushTargetType,
        target_ids: Iterable[int],
        subscription_key: str,
    ) -> list[int]:
        deduped_target_ids = list(
            dict.fromkeys(int(target_id) for target_id in target_ids)
        )
        if not deduped_target_ids:
            return []
        with self._connect() as con:
            placeholders = ",".join("?" for _ in deduped_target_ids)
            rows = con.execute(
                "SELECT target_id FROM push_unsubscriptions "
                "WHERE target_type = ? AND subscription_key = ? "
                f"AND target_id IN ({placeholders})",
                (target_type, subscription_key, *deduped_target_ids),
            ).fetchall()
        blocked = {int(row[0]) for row in rows}
        return [
            target_id for target_id in deduped_target_ids if target_id not in blocked
        ]

    def filter_subscribed_user_ids(
        self,
        user_ids: Iterable[int],
        subscription_key: str,
    ) -> list[int]:
        return self.filter_subscribed_target_ids("private", user_ids, subscription_key)

    def filter_subscribed_group_ids(
        self,
        group_ids: Iterable[int],
        subscription_key: str,
    ) -> list[int]:
        return self.filter_subscribed_target_ids("group", group_ids, subscription_key)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path)
        con.execute(
            "CREATE TABLE IF NOT EXISTS push_unsubscriptions ("
            "target_type TEXT NOT NULL, "
            "target_id INTEGER NOT NULL, "
            "subscription_key TEXT NOT NULL, "
            "feature TEXT NOT NULL, "
            "created_at TEXT NOT NULL, "
            "PRIMARY KEY (target_type, target_id, subscription_key)"
            ")"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_push_unsubscriptions_lookup "
            "ON push_unsubscriptions (target_type, subscription_key, target_id)"
        )
        con.commit()
        return con


def build_schedule_subscription_options(  # noqa: PLR0913
    *,
    target_type: PushTargetType,
    target_id: int,
    tasks: Sequence[ScheduledPushTask],
    eligible_target_ids_for_feature: dict[str, set[int]],
    store: PushUnsubscribeStore,
    include_unsubscribed: bool,
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
        if include_unsubscribed != is_unsubscribed:
            continue

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
            )
        )

    return options


def build_push_subscription_menu(
    *,
    title: str,
    options: Sequence[PushSubscriptionOption],
) -> str:
    lines = [title]
    lines.extend(
        f"{index}. {option.label}"
        for index, option in enumerate(options, start=1)
    )
    lines.append("")
    lines.append("💬 输入序号选择 · 输入 0 退出")
    return "\n".join(lines)

__all__ = [
    "BUILTIN_PUSH_OPTIONS",
    "PushSubscriptionOption",
    "PushTargetType",
    "PushUnsubscribeStore",
    "append_push_unsubscribe_hint",
    "build_push_subscription_menu",
    "build_schedule_subscription_options",
    "group_schedule_key",
    "private_schedule_key",
]
