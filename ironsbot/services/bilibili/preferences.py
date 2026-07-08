from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ironsbot.config.models.bilibili import BiliPushMode
    from ironsbot.shared.messaging.push_subscriptions import PushTargetType

BILI_PUSH_SUBSCRIPTION_PREFIX = "bili_push:"
BiliRuntimePushMode = Literal["full", "link"]
INVALID_PUSH_MODE_ERROR = "push mode must be content/full, link, or default"


def bili_push_subscription_key(uid: int) -> str:
    return f"{BILI_PUSH_SUBSCRIPTION_PREFIX}{int(uid)}"


def bili_push_subscription_label(uid: int, account: str | None = None) -> str:
    if account:
        return f"B站动态：{account}（{int(uid)}）"
    return f"B站动态：{int(uid)}"


def normalize_push_mode_text(raw_mode: str) -> BiliRuntimePushMode | None:
    mode = "".join(raw_mode.strip().lower().split())
    if mode in {"full", "content", "内容", "全文", "正文"}:
        return "full"
    if mode in {"link", "url", "链接", "只发链接"}:
        return "link"
    if mode in {"default", "reset", "默认", "重置"}:
        return None
    raise ValueError(INVALID_PUSH_MODE_ERROR)


def push_mode_label(mode: BiliPushMode | None) -> str:
    if mode == "full":
        return "内容"
    if mode == "link":
        return "链接"
    return "默认"


@dataclass(frozen=True, slots=True)
class BiliPushPreference:
    target_type: PushTargetType
    target_id: int
    uid: int
    mode: BiliRuntimePushMode
    updated_at: str


class BiliPushPreferenceStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def get_mode(
        self,
        target_type: PushTargetType,
        target_id: int,
        uid: int,
    ) -> BiliRuntimePushMode | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT mode FROM bili_push_preferences "
                "WHERE target_type = ? AND target_id = ? AND uid = ?",
                (target_type, int(target_id), int(uid)),
            ).fetchone()
        if row is None:
            return None
        mode = str(row[0])
        if mode == "full":
            return mode
        if mode == "link":
            return mode
        return None

    def set_mode(
        self,
        target_type: PushTargetType,
        target_id: int,
        uid: int,
        mode: BiliRuntimePushMode,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO bili_push_preferences "
                "(target_type, target_id, uid, mode, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (target_type, int(target_id), int(uid), mode, now),
            )
            con.commit()

    def clear_mode(
        self,
        target_type: PushTargetType,
        target_id: int,
        uid: int,
    ) -> None:
        with self._connect() as con:
            con.execute(
                "DELETE FROM bili_push_preferences "
                "WHERE target_type = ? AND target_id = ? AND uid = ?",
                (target_type, int(target_id), int(uid)),
            )
            con.commit()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path)
        con.execute(
            "CREATE TABLE IF NOT EXISTS bili_push_preferences ("
            "target_type TEXT NOT NULL, "
            "target_id INTEGER NOT NULL, "
            "uid INTEGER NOT NULL, "
            "mode TEXT NOT NULL, "
            "updated_at TEXT NOT NULL, "
            "PRIMARY KEY (target_type, target_id, uid)"
            ")"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_bili_push_preferences_uid "
            "ON bili_push_preferences (uid, target_type, target_id)"
        )
        con.commit()
        return con


__all__ = [
    "BILI_PUSH_SUBSCRIPTION_PREFIX",
    "BiliPushPreference",
    "BiliPushPreferenceStore",
    "bili_push_subscription_key",
    "bili_push_subscription_label",
    "normalize_push_mode_text",
    "push_mode_label",
]
