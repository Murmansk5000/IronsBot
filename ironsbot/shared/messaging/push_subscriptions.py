# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, cast

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.shared.selection_menu import (
    TOGGLE_SELECTION_FOOTER,
    SelectionMenuItem,
    format_selection_menu,
)
from ironsbot.shared.sqlite import open_sqlite

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Iterator, Sequence

    from ironsbot.config.models.message import PushUnsubscribeConfig

PushTargetType = Literal["private", "group"]
PushPreferenceType = Literal["cron_time", "activity_lead_hours"]
CRON_TIME_PREFERENCE: PushPreferenceType = "cron_time"
ACTIVITY_LEAD_HOURS_PREFERENCE: PushPreferenceType = "activity_lead_hours"
READONLY_SELECTION_FOOTER = "✅ 已订阅 · ❌ 已退订，普通群员仅可查看 · 输入 0 退出"


class ScheduledPushTask(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def enabled(self) -> bool: ...

    @property
    def feature(self) -> str: ...

    @property
    def message(self) -> str: ...

    @property
    def hour(self) -> int: ...

    @property
    def minute(self) -> int: ...

    @property
    def day_of_week(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class PushSubscriptionOption:
    key: str
    label: str
    feature: str
    unsubscribed: bool = False


@dataclass(frozen=True, slots=True)
class PushTimePreference:
    target_type: PushTargetType
    target_id: int
    subscription_key: str
    preference_type: PushPreferenceType
    value: str
    updated_at: str


BUILTIN_PUSH_OPTIONS: tuple[PushSubscriptionOption, ...] = (
    PushSubscriptionOption("seer_activity_push", "活动结束提醒", "seer_activity_push"),
    PushSubscriptionOption("server_status_push", "开服推送", "server_status_push"),
    PushSubscriptionOption("startup_notice", "机器人启动通知", "admin_notice"),
    PushSubscriptionOption("startup_docker_update", "启动镜像检查通知", "admin_notice"),
    PushSubscriptionOption("startup_data_sync", "启动数据同步通知", "admin_notice"),
    PushSubscriptionOption("ai_chat_error_notice", "AI聊天异常通知", "admin_notice"),
    PushSubscriptionOption("bili_login_notice", "B站登录通知", "admin_notice"),
    PushSubscriptionOption("headless_seer_notice", "无头赛尔号通知", "admin_notice"),
    PushSubscriptionOption("render_crash_notice", "精灵渲染崩溃通知", "admin_notice"),
    PushSubscriptionOption("red_packet_notice", "红包提醒", "admin_notice"),
    PushSubscriptionOption("admin_notice", "其他管理通知", "admin_notice"),
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
            rows = con.execute(
                "SELECT target_id FROM push_unsubscriptions "
                "WHERE target_type = ? AND subscription_key = ?",
                (target_type, subscription_key),
            ).fetchall()
        requested = set(deduped_target_ids)
        blocked = {int(row[0]) for row in rows if int(row[0]) in requested}
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

    def get_time_preference(
        self,
        target_type: PushTargetType,
        target_id: int,
        subscription_key: str,
        preference_type: PushPreferenceType,
    ) -> str | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT value FROM push_time_preferences "
                "WHERE target_type = ? AND target_id = ? "
                "AND subscription_key = ? AND preference_type = ?",
                (target_type, int(target_id), subscription_key, preference_type),
            ).fetchone()
        return None if row is None else str(row[0])

    def set_time_preference(
        self,
        target_type: PushTargetType,
        target_id: int,
        subscription_key: str,
        preference_type: PushPreferenceType,
        value: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO push_time_preferences "
                "(target_type, target_id, subscription_key, preference_type, "
                "value, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    target_type,
                    int(target_id),
                    subscription_key,
                    preference_type,
                    value,
                    now,
                ),
            )

    def clear_time_preference(
        self,
        target_type: PushTargetType,
        target_id: int,
        subscription_key: str,
        preference_type: PushPreferenceType,
    ) -> None:
        with self._connect() as con:
            con.execute(
                "DELETE FROM push_time_preferences "
                "WHERE target_type = ? AND target_id = ? "
                "AND subscription_key = ? AND preference_type = ?",
                (target_type, int(target_id), subscription_key, preference_type),
            )

    def target_time_preferences(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> dict[tuple[str, PushPreferenceType], str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT subscription_key, preference_type, value "
                "FROM push_time_preferences "
                "WHERE target_type = ? AND target_id = ?",
                (target_type, int(target_id)),
            ).fetchall()
        preferences: dict[tuple[str, PushPreferenceType], str] = {}
        for key, preference_type, value in rows:
            preference_type_text = str(preference_type)
            if preference_type_text not in {"cron_time", "activity_lead_hours"}:
                continue
            preferences[
                (str(key), cast("PushPreferenceType", preference_type_text))
            ] = str(value)
        return preferences

    def all_time_preferences(
        self,
        *,
        target_type: PushTargetType | None = None,
        subscription_key: str | None = None,
        preference_type: PushPreferenceType | None = None,
    ) -> list[PushTimePreference]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT target_type, target_id, subscription_key, preference_type, "
                "value, updated_at FROM push_time_preferences "
                "WHERE (? IS NULL OR target_type = ?) "
                "AND (? IS NULL OR subscription_key = ?) "
                "AND (? IS NULL OR preference_type = ?)",
                (
                    target_type,
                    target_type,
                    subscription_key,
                    subscription_key,
                    preference_type,
                    preference_type,
                ),
            ).fetchall()
        return [
            PushTimePreference(
                target_type=target_type_row,
                target_id=int(target_id),
                subscription_key=str(key),
                preference_type=preference_type_row,
                value=str(value),
                updated_at=str(updated_at),
            )
            for (
                target_type_row,
                target_id,
                key,
                preference_type_row,
                value,
                updated_at,
            ) in rows
            if target_type_row in {"private", "group"}
            and preference_type_row in {"cron_time", "activity_lead_hours"}
        ]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with open_sqlite(self.path) as con:
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
            con.execute(
                "CREATE TABLE IF NOT EXISTS push_time_preferences ("
                "target_type TEXT NOT NULL, "
                "target_id INTEGER NOT NULL, "
                "subscription_key TEXT NOT NULL, "
                "preference_type TEXT NOT NULL, "
                "value TEXT NOT NULL, "
                "updated_at TEXT NOT NULL, "
                "PRIMARY KEY ("
                "target_type, target_id, subscription_key, preference_type"
                ")"
                ")"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_push_time_preferences_lookup "
                "ON push_time_preferences "
                "(target_type, subscription_key, preference_type, target_id)"
            )
            yield con


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
    "ACTIVITY_LEAD_HOURS_PREFERENCE",
    "BUILTIN_PUSH_OPTIONS",
    "CRON_TIME_PREFERENCE",
    "PushPreferenceType",
    "PushSubscriptionOption",
    "PushTargetType",
    "PushTimePreference",
    "PushUnsubscribeStore",
    "append_push_unsubscribe_hint",
    "build_push_subscription_menu",
    "build_schedule_subscription_options",
    "group_schedule_key",
    "private_schedule_key",
]
