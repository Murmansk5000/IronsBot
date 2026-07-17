# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.shared.sqlite import open_sqlite_schema

if TYPE_CHECKING:
    from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS player_bindings (
    qq_user_id INTEGER PRIMARY KEY,
    player_id INTEGER,
    player_nick TEXT,
    choice_completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_YES_REPLIES = frozenset(("是", "yes", "y", "确认", "确定"))
_NO_REPLIES = frozenset(("否", "no", "n", "取消"))
_BINDING_COMMAND_RE = re.compile(r"^(?:绑定米米号|更改米米号)(\d+)$")


@dataclass(frozen=True, slots=True)
class PlayerBindingState:
    qq_user_id: int
    player_id: int | None = None
    player_nick: str = ""
    choice_completed: bool = False

    @property
    def is_bound(self) -> bool:
        return self.player_id is not None


def parse_binding_choice(text: str) -> bool | None:
    normalized = text.strip().casefold()
    if normalized in _YES_REPLIES:
        return True
    if normalized in _NO_REPLIES:
        return False
    return None


def parse_player_binding_target(text: str) -> int | None:
    match = _BINDING_COMMAND_RE.fullmatch(text.strip())
    return int(match.group(1)) if match is not None else None


def player_binding_offer_message(player_id: int, nick: str) -> str:
    return (
        f"已查到米米号：{player_id}（{nick}）\n\n"
        "是否将其设为默认米米号？\n"
        "回复“是”或“y”确认，回复“否”或“n”跳过。\n"
        "设置后发送“米米号 / 收集 / 巅峰 / 群星牌”即可快捷查询。\n"
        "以后可发送“解绑米米号”解除绑定。"
    )


def get_player_binding(path: str | Path, qq_user_id: int) -> PlayerBindingState:
    with open_sqlite_schema(path, _SCHEMA) as conn:
        row = conn.execute(
            """
            SELECT player_id, player_nick, choice_completed
            FROM player_bindings
            WHERE qq_user_id = ?
            """,
            (qq_user_id,),
        ).fetchone()
    if row is None:
        return PlayerBindingState(qq_user_id=qq_user_id)
    return PlayerBindingState(
        qq_user_id=qq_user_id,
        player_id=None if row[0] is None else int(row[0]),
        player_nick=str(row[1] or ""),
        choice_completed=bool(row[2]),
    )


def bind_player(
    path: str | Path,
    *,
    qq_user_id: int,
    player_id: int,
    player_nick: str,
) -> None:
    now = _utc_now()
    with open_sqlite_schema(path, _SCHEMA) as conn:
        conn.execute(
            """
            INSERT INTO player_bindings(
                qq_user_id, player_id, player_nick,
                choice_completed, created_at, updated_at
            )
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(qq_user_id) DO UPDATE SET
                player_id = excluded.player_id,
                player_nick = excluded.player_nick,
                choice_completed = 1,
                updated_at = excluded.updated_at
            """,
            (qq_user_id, player_id, player_nick, now, now),
        )


def decline_player_binding(path: str | Path, *, qq_user_id: int) -> None:
    now = _utc_now()
    with open_sqlite_schema(path, _SCHEMA) as conn:
        conn.execute(
            """
            INSERT INTO player_bindings(
                qq_user_id, player_id, player_nick,
                choice_completed, created_at, updated_at
            )
            VALUES (?, NULL, '', 1, ?, ?)
            ON CONFLICT(qq_user_id) DO UPDATE SET
                choice_completed = 1,
                updated_at = excluded.updated_at
            """,
            (qq_user_id, now, now),
        )


def unbind_player(path: str | Path, *, qq_user_id: int) -> bool:
    now = _utc_now()
    with open_sqlite_schema(path, _SCHEMA) as conn:
        cursor = conn.execute(
            """
            UPDATE player_bindings
            SET player_id = NULL, player_nick = '',
                choice_completed = 1, updated_at = ?
            WHERE qq_user_id = ? AND player_id IS NOT NULL
            """,
            (now, qq_user_id),
        )
        return cursor.rowcount > 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "PlayerBindingState",
    "bind_player",
    "decline_player_binding",
    "get_player_binding",
    "parse_binding_choice",
    "parse_player_binding_target",
    "player_binding_offer_message",
    "unbind_player",
]
