# SPDX-License-Identifier: MIT
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ironsbot.config.models.message import PrivateUnsubscribeConfig

from .runtime_service import build_schedule_job_id


class PrivateScheduleTask(Protocol):
    id: str
    enabled: bool
    feature: str
    message: str
    hour: int
    minute: int
    day_of_week: str | None


@dataclass(frozen=True, slots=True)
class PrivateScheduleSubscriptionOption:
    key: str
    label: str
    feature: str


def private_schedule_key(index: int, task: PrivateScheduleTask) -> str:
    raw_id = task.id.strip()
    if raw_id:
        return raw_id
    return build_schedule_job_id("private_schedule", index, "")


def private_schedule_label(index: int, task: PrivateScheduleTask) -> str:
    name = task.id.strip() or f"私聊推送 {index}"
    time_label = f"{task.hour:02d}:{task.minute:02d}"
    if task.day_of_week:
        time_label = f"{task.day_of_week} {time_label}"
    return f"{name}（{time_label}，feature: {task.feature}）"


def append_private_unsubscribe_hint(
    message: str,
    config: PrivateUnsubscribeConfig,
) -> str:
    text = message.rstrip()
    if not config.enabled:
        return text
    hint = config.hint.strip()
    if not hint or hint in text:
        return text
    if not text:
        return hint
    return f"{text}\n\n{hint}"


class PrivatePushUnsubscribeStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def unsubscribed_keys(self, user_id: int) -> set[str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT schedule_key FROM private_push_unsubscriptions "
                "WHERE user_id = ?",
                (int(user_id),),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def is_unsubscribed(self, user_id: int, schedule_key: str) -> bool:
        with self._connect() as con:
            row = con.execute(
                "SELECT 1 FROM private_push_unsubscriptions "
                "WHERE user_id = ? AND schedule_key = ?",
                (int(user_id), schedule_key),
            ).fetchone()
        return row is not None

    def unsubscribe(self, user_id: int, schedule_key: str, feature: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO private_push_unsubscriptions "
                "(user_id, schedule_key, feature, created_at) "
                "VALUES (?, ?, ?, ?)",
                (int(user_id), schedule_key, feature, now),
            )
            con.commit()

    def restore(self, user_id: int, schedule_key: str) -> None:
        with self._connect() as con:
            con.execute(
                "DELETE FROM private_push_unsubscriptions "
                "WHERE user_id = ? AND schedule_key = ?",
                (int(user_id), schedule_key),
            )
            con.commit()

    def filter_subscribed_user_ids(
        self,
        user_ids: Iterable[int],
        schedule_key: str,
    ) -> list[int]:
        deduped_user_ids = list(dict.fromkeys(int(user_id) for user_id in user_ids))
        if not deduped_user_ids:
            return []
        with self._connect() as con:
            placeholders = ",".join("?" for _ in deduped_user_ids)
            rows = con.execute(
                "SELECT user_id FROM private_push_unsubscriptions "
                f"WHERE schedule_key = ? AND user_id IN ({placeholders})",
                (schedule_key, *deduped_user_ids),
            ).fetchall()
        blocked = {int(row[0]) for row in rows}
        return [user_id for user_id in deduped_user_ids if user_id not in blocked]

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path)
        con.execute(
            "CREATE TABLE IF NOT EXISTS private_push_unsubscriptions ("
            "user_id INTEGER NOT NULL, "
            "schedule_key TEXT NOT NULL, "
            "feature TEXT NOT NULL, "
            "created_at TEXT NOT NULL, "
            "PRIMARY KEY (user_id, schedule_key)"
            ")"
        )
        return con


def build_private_schedule_options(
    *,
    user_id: int,
    tasks: Sequence[PrivateScheduleTask],
    eligible_user_ids_for_feature: dict[str, set[int]],
    store: PrivatePushUnsubscribeStore,
    include_unsubscribed: bool,
) -> list[PrivateScheduleSubscriptionOption]:
    unsubscribed = store.unsubscribed_keys(user_id)
    options: list[PrivateScheduleSubscriptionOption] = []

    for index, task in enumerate(tasks, start=1):
        if not task.enabled:
            continue
        if user_id not in eligible_user_ids_for_feature.get(task.feature, set()):
            continue

        key = private_schedule_key(index, task)
        is_unsubscribed = key in unsubscribed
        if include_unsubscribed != is_unsubscribed:
            continue

        options.append(
            PrivateScheduleSubscriptionOption(
                key=key,
                label=private_schedule_label(index, task),
                feature=task.feature,
            )
        )

    return options


def build_private_schedule_menu(
    *,
    title: str,
    options: Sequence[PrivateScheduleSubscriptionOption],
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
    "PrivatePushUnsubscribeStore",
    "PrivateScheduleSubscriptionOption",
    "append_private_unsubscribe_hint",
    "build_private_schedule_menu",
    "build_private_schedule_options",
    "private_schedule_key",
    "private_schedule_label",
]
