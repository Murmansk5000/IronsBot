# SPDX-License-Identifier: MIT
"""Platform-neutral storage for team-audit follow-up reminders."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    require_sqlite_columns,
)
from ironsbot.services.team.audit import TeamAuditPendingReminder

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.platform import ActorRef, ConversationRef


_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_team_audit_reminders (
    conversation_platform TEXT NOT NULL,
    conversation_account_id TEXT NOT NULL DEFAULT '',
    conversation_kind TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    actor_platform TEXT NOT NULL,
    actor_account_id TEXT NOT NULL DEFAULT '',
    actor_kind TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_scope_id TEXT NOT NULL DEFAULT '',
    joined_at TEXT NOT NULL,
    remind_at TEXT NOT NULL,
    step INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (
        conversation_platform, conversation_account_id, conversation_kind,
        conversation_id, actor_platform, actor_account_id, actor_kind, actor_id,
        actor_scope_id
    )
)
"""
_MIGRATIONS = (
    SqliteMigration(1, (_SCHEMA,)),
    SqliteMigration(
        2,
        callback=require_sqlite_columns(
            "pending_team_audit_reminders",
            {"actor_account_id", "conversation_account_id"},
        ),
    ),
)
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
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_team_audit_reminders (
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id,
                    actor_platform, actor_account_id, actor_kind, actor_id,
                    actor_scope_id,
                    joined_at, remind_at, step
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id,
                    actor_platform, actor_account_id, actor_kind, actor_id,
                    actor_scope_id
                ) DO UPDATE SET
                    joined_at = excluded.joined_at,
                    remind_at = excluded.remind_at,
                    step = excluded.step
                """,
                (
                    *_conversation_values(reminder.conversation),
                    *_actor_values(reminder.actor),
                    _datetime_text(reminder.joined_at),
                    _datetime_text(reminder.remind_at),
                    reminder.step,
                ),
            )

    def get(
        self,
        conversation: ConversationRef,
        actor: ActorRef,
    ) -> TeamAuditPendingReminder | None:
        with self._database.connect() as conn:
            row = conn.execute(
                """
                SELECT conversation_platform, conversation_account_id,
                       conversation_kind, conversation_id,
                       actor_platform, actor_account_id, actor_kind, actor_id,
                       actor_scope_id,
                       joined_at, remind_at, step
                FROM pending_team_audit_reminders
                WHERE conversation_platform = ?
                  AND conversation_account_id = ?
                  AND conversation_kind = ? AND conversation_id = ?
                  AND actor_platform = ? AND actor_account_id = ?
                  AND actor_kind = ? AND actor_id = ? AND actor_scope_id = ?
                """,
                (
                    *_conversation_values(conversation),
                    *_actor_values(actor),
                ),
            ).fetchone()
        return None if row is None else _row_to_reminder(row)

    def list_all(self) -> list[TeamAuditPendingReminder]:
        with self._database.connect() as conn:
            rows = conn.execute(
                """
                SELECT conversation_platform, conversation_account_id,
                       conversation_kind, conversation_id,
                       actor_platform, actor_account_id, actor_kind, actor_id,
                       actor_scope_id,
                       joined_at, remind_at, step
                FROM pending_team_audit_reminders
                ORDER BY remind_at, conversation_id, actor_id
                """
            ).fetchall()
        return [_row_to_reminder(row) for row in rows]

    def clear(self, conversation: ConversationRef, actor: ActorRef) -> None:
        with self._database.connect() as conn:
            conn.execute(
                """
                DELETE FROM pending_team_audit_reminders
                WHERE conversation_platform = ?
                  AND conversation_account_id = ?
                  AND conversation_kind = ? AND conversation_id = ?
                  AND actor_platform = ? AND actor_account_id = ?
                  AND actor_kind = ? AND actor_id = ? AND actor_scope_id = ?
                """,
                (
                    *_conversation_values(conversation),
                    *_actor_values(actor),
                ),
            )


def _row_to_reminder(row: sqlite3.Row) -> TeamAuditPendingReminder:
    conversation = ConversationIdentityColumns(
        row["conversation_platform"],
        row["conversation_account_id"],
        row["conversation_kind"],
        row["conversation_id"],
    ).to_conversation()
    actor = ActorIdentityColumns(
        row["actor_platform"],
        row["actor_account_id"],
        row["actor_kind"],
        row["actor_id"],
        row["actor_scope_id"],
    ).to_actor()
    return TeamAuditPendingReminder(
        conversation,
        actor,
        _parse_datetime(str(row["joined_at"])),
        _parse_datetime(str(row["remind_at"])),
        max(1, int(row["step"])),
    )


def _conversation_values(conversation: ConversationRef) -> tuple[str, str, str, str]:
    return ConversationIdentityColumns.from_conversation(conversation).values()


def _actor_values(actor: ActorRef) -> tuple[str, str, str, str, str]:
    return ActorIdentityColumns.from_actor(actor).values()


def _datetime_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
