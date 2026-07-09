# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.config.loader import get_app_config
from ironsbot.shared.sqlite import open_sqlite_schema

if TYPE_CHECKING:
    from contextlib import AbstractContextManager
    from pathlib import Path

    from ironsbot.config.models.seer import RankQueryConfig


@dataclass(frozen=True, slots=True)
class RankDisplayLimitCommand:
    limit: int


RANK_DISPLAY_LIMIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS group_rank_display_limits (
    group_id INTEGER PRIMARY KEY,
    display_limit INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by INTEGER NOT NULL
)
"""


def rank_display_limit_for_group(group_id: int | None) -> int:
    config = get_app_config().seer.rank
    return _clamp_limit(
        _stored_group_limit(group_id)
        or _configured_group_limit(config, group_id)
        or config.display_limit,
        config,
    )


def set_group_rank_display_limit(
    group_id: int,
    user_id: int,
    limit: int,
) -> None:
    config = get_app_config().seer.rank
    limit = _clamp_limit(limit, config)
    now = datetime.now(timezone.utc).isoformat()
    with _connect(config.display_limit_path) as conn:
        conn.execute(
            """
            INSERT INTO group_rank_display_limits (
                group_id, display_limit, updated_at, updated_by
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                display_limit = excluded.display_limit,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (group_id, limit, now, user_id),
        )


def parse_rank_display_limit_command(text: str) -> RankDisplayLimitCommand | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    command = "".join(stripped[1:].split()).lower()
    prefixes = (
        "榜单显示条数",
        "榜单显示数量",
        "榜单默认条数",
        "榜单默认数量",
        "榜单显示",
        "榜单条数",
    )
    prefix = next((item for item in prefixes if command.startswith(item)), None)
    if prefix is None:
        return None

    value = command[len(prefix) :]
    match = re.fullmatch(r"(\d+)(?:名|条)?", value)
    if match is None:
        return None
    return RankDisplayLimitCommand(limit=int(match.group(1)))


def build_rank_display_limit_message(
    *,
    group_id: int,
    limit: int,
) -> str:
    return f"✅ 本群榜单默认显示条数已设置为 {limit} 名（群号：{group_id}）。"


def build_rank_display_limit_denied_message() -> str:
    return "❌ 只有本群群主、管理员或超级管理员可以修改榜单默认显示条数。"


def build_rank_display_limit_invalid_message(limit: int) -> str:
    config = get_app_config().seer.rank
    return (
        f"❌ 榜单默认显示条数必须在 1~{config.max_display_limit} 之间，"
        f"当前输入：{limit}。"
    )


def _configured_group_limit(
    config: RankQueryConfig,
    group_id: int | None,
) -> int | None:
    if group_id is None:
        return None

    direct = config.display_limits.get(str(group_id))
    if direct is not None:
        return direct

    aliases = get_app_config().feature.group_aliases
    for alias, alias_group_id in aliases.items():
        if alias_group_id == group_id and alias in config.display_limits:
            return config.display_limits[alias]
    return None


def _stored_group_limit(group_id: int | None) -> int | None:
    if group_id is None:
        return None

    config = get_app_config().seer.rank
    try:
        with _connect(config.display_limit_path) as conn:
            row = conn.execute(
                """
                SELECT display_limit
                FROM group_rank_display_limits
                WHERE group_id = ?
                """,
                (group_id,),
            ).fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row is not None else None


def _connect(path: Path) -> AbstractContextManager[sqlite3.Connection]:
    return open_sqlite_schema(path, RANK_DISPLAY_LIMIT_SCHEMA)


def _clamp_limit(value: int, config: RankQueryConfig) -> int:
    return max(1, min(int(value), config.max_display_limit))
