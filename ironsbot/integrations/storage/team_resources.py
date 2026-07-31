# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration
from ironsbot.services.team.resource import (
    TeamResourcePrivateSubscription,
    TeamResourcePrivateSubscriptionUpdate,
    TeamResourceSubscription,
    TeamResourceSubscriptionPrompt,
    TeamResourceSubscriptionUpdate,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS team_resource_subscriptions (
        group_id INTEGER NOT NULL,
        team_id INTEGER NOT NULL,
        team_name TEXT NOT NULL DEFAULT '',
        threshold INTEGER NOT NULL,
        at_user_ids TEXT NOT NULL DEFAULT '',
        created_by INTEGER NOT NULL,
        updated_by INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (group_id, team_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_team_resource_subscriptions_group
    ON team_resource_subscriptions (group_id, team_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS team_resource_subscription_prompts (
        group_id INTEGER PRIMARY KEY,
        team_id INTEGER NOT NULL,
        team_name TEXT NOT NULL DEFAULT '',
        prompted_by INTEGER NOT NULL,
        prompted_at TEXT NOT NULL,
        handled_by INTEGER,
        handled_at TEXT,
        accepted INTEGER
    )
    """,
)
PRIVATE_SUBSCRIPTION_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS team_resource_private_subscriptions (
        user_id INTEGER NOT NULL,
        team_id INTEGER NOT NULL,
        team_name TEXT NOT NULL DEFAULT '',
        threshold INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (user_id, team_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_team_resource_private_subscriptions_user
    ON team_resource_private_subscriptions (user_id, team_id)
    """,
)
MIGRATIONS = (
    SqliteMigration(1, SCHEMA),
    SqliteMigration(2, PRIVATE_SUBSCRIPTION_SCHEMA),
)


class TeamResourceSubscriptionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = path

    def list_all(self) -> list[TeamResourceSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT group_id, team_id, team_name, threshold, at_user_ids,
                       created_by, updated_by, created_at, updated_at
                FROM team_resource_subscriptions
                ORDER BY group_id, team_id
                """
            ).fetchall()
        return [_row_to_subscription(row) for row in rows]

    def list_group(self, group_id: int) -> list[TeamResourceSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT group_id, team_id, team_name, threshold, at_user_ids,
                       created_by, updated_by, created_at, updated_at
                FROM team_resource_subscriptions
                WHERE group_id = ?
                ORDER BY team_id
                """,
                (group_id,),
            ).fetchall()
        return [_row_to_subscription(row) for row in rows]

    def upsert(self, update: TeamResourceSubscriptionUpdate) -> None:
        now = _now_text()
        at_text = _encode_user_ids(update.at_user_ids)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO team_resource_subscriptions (
                    group_id, team_id, team_name, threshold, at_user_ids,
                    created_by, updated_by, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(group_id, team_id) DO UPDATE SET
                    team_name = excluded.team_name,
                    threshold = excluded.threshold,
                    at_user_ids = excluded.at_user_ids,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (
                    update.group_id,
                    update.team_id,
                    update.team_name.strip(),
                    update.threshold,
                    at_text,
                    update.operator_id,
                    update.operator_id,
                    now,
                    now,
                ),
            )

    def list_all_private(self) -> list[TeamResourcePrivateSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id, team_id, team_name, threshold, created_at, updated_at
                FROM team_resource_private_subscriptions
                ORDER BY user_id, team_id
                """
            ).fetchall()
        return [_row_to_private_subscription(row) for row in rows]

    def list_user(self, user_id: int) -> list[TeamResourcePrivateSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id, team_id, team_name, threshold, created_at, updated_at
                FROM team_resource_private_subscriptions
                WHERE user_id = ?
                ORDER BY team_id
                """,
                (user_id,),
            ).fetchall()
        return [_row_to_private_subscription(row) for row in rows]

    def upsert_private(self, update: TeamResourcePrivateSubscriptionUpdate) -> None:
        now = _now_text()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO team_resource_private_subscriptions (
                    user_id, team_id, team_name, threshold, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, team_id) DO UPDATE SET
                    team_name = excluded.team_name,
                    threshold = excluded.threshold,
                    updated_at = excluded.updated_at
                """,
                (
                    update.user_id,
                    update.team_id,
                    update.team_name.strip(),
                    update.threshold,
                    now,
                    now,
                ),
            )

    def has_prompted_group(self, group_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM team_resource_subscription_prompts
                WHERE group_id = ?
                """,
                (group_id,),
            ).fetchone()
        return row is not None

    def get_pending_prompt(
        self,
        group_id: int,
    ) -> TeamResourceSubscriptionPrompt | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT group_id, team_id, team_name, prompted_by, prompted_at,
                       handled_by, handled_at, accepted
                FROM team_resource_subscription_prompts
                WHERE group_id = ? AND handled_at IS NULL
                """,
                (group_id,),
            ).fetchone()
        return _row_to_prompt(row) if row is not None else None

    def mark_group_prompted(
        self,
        *,
        group_id: int,
        team_id: int,
        team_name: str,
        prompted_by: int,
    ) -> None:
        now = _now_text()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO team_resource_subscription_prompts (
                    group_id, team_id, team_name, prompted_by, prompted_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (group_id, team_id, team_name.strip(), prompted_by, now),
            )

    def mark_prompt_handled(
        self,
        *,
        group_id: int,
        handled_by: int,
        accepted: bool,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE team_resource_subscription_prompts
                SET handled_by = ?, handled_at = ?, accepted = ?
                WHERE group_id = ? AND handled_at IS NULL
                """,
                (handled_by, _now_text(), int(accepted), group_id),
            )

    def update_team_name(
        self,
        *,
        group_id: int,
        team_id: int,
        team_name: str,
    ) -> None:
        if not team_name.strip():
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE team_resource_subscriptions
                SET team_name = ?, updated_at = ?
                WHERE group_id = ? AND team_id = ?
                """,
                (team_name.strip(), _now_text(), group_id, team_id),
            )

    def delete(self, *, group_id: int, team_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM team_resource_subscriptions
                WHERE group_id = ? AND team_id = ?
                """,
                (group_id, team_id),
            )
            return cursor.rowcount > 0

    def update_private_team_name(
        self,
        *,
        user_id: int,
        team_id: int,
        team_name: str,
    ) -> None:
        if not team_name.strip():
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE team_resource_private_subscriptions
                SET team_name = ?, updated_at = ?
                WHERE user_id = ? AND team_id = ?
                """,
                (team_name.strip(), _now_text(), user_id, team_id),
            )

    def delete_private(self, *, user_id: int, team_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM team_resource_private_subscriptions
                WHERE user_id = ? AND team_id = ?
                """,
                (user_id, team_id),
            )
            return cursor.rowcount > 0

    def _connect(self):
        return SqliteDatabase(
            self.path,
            migrations=MIGRATIONS,
        ).connect()

def _row_to_subscription(
    row: tuple[Any, ...],
) -> TeamResourceSubscription:
    return TeamResourceSubscription(
        group_id=int(row[0]),
        team_id=int(row[1]),
        team_name=str(row[2] or ""),
        threshold=int(row[3]),
        at_user_ids=_decode_user_ids(str(row[4] or "")),
        created_by=int(row[5]),
        updated_by=int(row[6]),
        created_at=str(row[7]),
        updated_at=str(row[8]),
    )


def _row_to_private_subscription(
    row: tuple[Any, ...],
) -> TeamResourcePrivateSubscription:
    return TeamResourcePrivateSubscription(
        user_id=int(row[0]),
        team_id=int(row[1]),
        team_name=str(row[2] or ""),
        threshold=int(row[3]),
        created_at=str(row[4]),
        updated_at=str(row[5]),
    )


def _row_to_prompt(
    row: tuple[Any, ...],
) -> TeamResourceSubscriptionPrompt:
    return TeamResourceSubscriptionPrompt(
        group_id=int(row[0]),
        team_id=int(row[1]),
        team_name=str(row[2] or ""),
        prompted_by=int(row[3]),
        prompted_at=str(row[4]),
        handled_by=None if row[5] is None else int(row[5]),
        handled_at=None if row[6] is None else str(row[6]),
        accepted=None if row[7] is None else bool(row[7]),
    )


def _encode_user_ids(user_ids: tuple[int, ...]) -> str:
    return ",".join(str(user_id) for user_id in dict.fromkeys(user_ids))


def _decode_user_ids(value: str) -> tuple[int, ...]:
    user_ids: list[int] = []
    for item in value.split(","):
        raw = item.strip()
        if raw.isdigit():
            user_ids.append(int(raw))
    return tuple(dict.fromkeys(user_ids))


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
