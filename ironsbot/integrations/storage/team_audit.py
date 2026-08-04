# SPDX-License-Identifier: MIT
"""Platform-neutral storage for team-audit follow-up reminders."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration
from ironsbot.services.team.audit import TeamAuditPendingReminder

if TYPE_CHECKING:
    from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_team_audit_reminders (
    conversation_platform TEXT NOT NULL,
    conversation_kind TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    actor_platform TEXT NOT NULL,
    actor_kind TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_scope_id TEXT NOT NULL DEFAULT '',
    joined_at TEXT NOT NULL,
    remind_at TEXT NOT NULL,
    step INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (
        conversation_platform, conversation_kind, conversation_id,
        actor_platform, actor_kind, actor_id, actor_scope_id
    )
)
"""
_MIGRATIONS = (SqliteMigration(1, (_SCHEMA,)),)
MIGRATION_NAMESPACE = "team_audit"


class SqliteTeamAuditReminderStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
            row_factory=sqlite3.Row,
        )

    def save(self, reminder: TeamAuditPendingReminder) -> None:
        conversation = _group_conversation(reminder.group_id)
        actor = _member_actor(reminder.group_id, reminder.user_id)
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_team_audit_reminders (
                    conversation_platform, conversation_kind, conversation_id,
                    actor_platform, actor_kind, actor_id, actor_scope_id,
                    joined_at, remind_at, step
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    conversation_platform, conversation_kind, conversation_id,
                    actor_platform, actor_kind, actor_id, actor_scope_id
                ) DO UPDATE SET
                    joined_at = excluded.joined_at,
                    remind_at = excluded.remind_at,
                    step = excluded.step
                """,
                (
                    *_conversation_values(conversation),
                    *_actor_values(actor),
                    _datetime_text(reminder.joined_at),
                    _datetime_text(reminder.remind_at),
                    reminder.step,
                ),
            )

    def get(
        self,
        group_id: int,
        user_id: int,
    ) -> TeamAuditPendingReminder | None:
        with self._database.connect() as conn:
            row = conn.execute(
                """
                SELECT conversation_platform, conversation_kind, conversation_id,
                       actor_platform, actor_kind, actor_id, actor_scope_id,
                       joined_at, remind_at, step
                FROM pending_team_audit_reminders
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND actor_platform = ?
                  AND actor_kind = ? AND actor_id = ? AND actor_scope_id = ?
                """,
                (
                    *_conversation_values(_group_conversation(group_id)),
                    *_actor_values(_member_actor(group_id, user_id)),
                ),
            ).fetchone()
        return None if row is None else _row_to_reminder(row)

    def list_all(self) -> list[TeamAuditPendingReminder]:
        with self._database.connect() as conn:
            rows = conn.execute(
                """
                SELECT conversation_platform, conversation_kind, conversation_id,
                       actor_platform, actor_kind, actor_id, actor_scope_id,
                       joined_at, remind_at, step
                FROM pending_team_audit_reminders
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND actor_platform = ? AND actor_kind = ?
                ORDER BY remind_at, conversation_id, actor_id
                """,
                (Platform.ONEBOT.value, "group", Platform.ONEBOT.value, "member"),
            ).fetchall()
        return [_row_to_reminder(row) for row in rows]

    def clear(self, group_id: int, user_id: int) -> None:
        with self._database.connect() as conn:
            conn.execute(
                """
                DELETE FROM pending_team_audit_reminders
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND actor_platform = ?
                  AND actor_kind = ? AND actor_id = ? AND actor_scope_id = ?
                """,
                (
                    *_conversation_values(_group_conversation(group_id)),
                    *_actor_values(_member_actor(group_id, user_id)),
                ),
            )


def _row_to_reminder(row: sqlite3.Row) -> TeamAuditPendingReminder:
    conversation = ConversationIdentityColumns(
        row["conversation_platform"],
        row["conversation_kind"],
        row["conversation_id"],
    ).to_conversation()
    actor = ActorIdentityColumns(
        row["actor_platform"],
        row["actor_kind"],
        row["actor_id"],
        row["actor_scope_id"],
    ).to_actor()
    return TeamAuditPendingReminder(
        _onebot_group_id(conversation),
        _onebot_user_id(actor),
        _parse_datetime(str(row["joined_at"])),
        _parse_datetime(str(row["remind_at"])),
        max(1, int(row["step"])),
    )


def _group_conversation(group_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(int(group_id)))


def _member_actor(group_id: int, user_id: int) -> ActorRef:
    return ActorRef(
        Platform.ONEBOT,
        str(int(user_id)),
        kind="member",
        scope_id=str(int(group_id)),
    )


def _conversation_values(conversation: ConversationRef) -> tuple[str, str, str]:
    return ConversationIdentityColumns.from_conversation(conversation).values()


def _actor_values(actor: ActorRef) -> tuple[str, str, str, str]:
    return ActorIdentityColumns.from_actor(actor).values()


def _onebot_group_id(conversation: ConversationRef) -> int:
    if conversation.platform is not Platform.ONEBOT or conversation.kind != "group":
        raise ValueError
    return int(conversation.id)


def _onebot_user_id(actor: ActorRef) -> int:
    if actor.platform is not Platform.ONEBOT or actor.kind != "member":
        raise ValueError
    return int(actor.id)


def _datetime_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
