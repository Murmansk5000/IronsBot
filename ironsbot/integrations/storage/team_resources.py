# SPDX-License-Identifier: MIT
"""Platform-neutral persistence for team resource subscriptions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration
from ironsbot.services.team.resource_subscriptions import (
    TeamResourcePrivateSubscription,
    TeamResourcePrivateSubscriptionUpdate,
    TeamResourceSubscription,
    TeamResourceSubscriptionPrompt,
    TeamResourceSubscriptionUpdate,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from ironsbot.core.platform import ActorRef, ConversationRef


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS team_resource_subscriptions (
        conversation_platform TEXT NOT NULL,
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        team_id INTEGER NOT NULL,
        team_name TEXT NOT NULL DEFAULT '',
        threshold INTEGER NOT NULL,
        created_by_platform TEXT NOT NULL,
        created_by_kind TEXT NOT NULL,
        created_by_id TEXT NOT NULL,
        created_by_scope_id TEXT NOT NULL DEFAULT '',
        updated_by_platform TEXT NOT NULL,
        updated_by_kind TEXT NOT NULL,
        updated_by_id TEXT NOT NULL,
        updated_by_scope_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (
            conversation_platform, conversation_kind, conversation_id, team_id
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS team_resource_subscription_mentions (
        conversation_platform TEXT NOT NULL,
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        team_id INTEGER NOT NULL,
        actor_platform TEXT NOT NULL,
        actor_kind TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        actor_scope_id TEXT NOT NULL DEFAULT '',
        position INTEGER NOT NULL,
        PRIMARY KEY (
            conversation_platform, conversation_kind, conversation_id, team_id,
            actor_platform, actor_kind, actor_id, actor_scope_id
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS team_resource_private_subscriptions (
        actor_platform TEXT NOT NULL,
        actor_kind TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        actor_scope_id TEXT NOT NULL DEFAULT '',
        team_id INTEGER NOT NULL,
        team_name TEXT NOT NULL DEFAULT '',
        threshold INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (actor_platform, actor_kind, actor_id, actor_scope_id, team_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS team_resource_subscription_prompts (
        conversation_platform TEXT NOT NULL,
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        team_id INTEGER NOT NULL,
        team_name TEXT NOT NULL DEFAULT '',
        prompted_by_platform TEXT NOT NULL,
        prompted_by_kind TEXT NOT NULL,
        prompted_by_id TEXT NOT NULL,
        prompted_by_scope_id TEXT NOT NULL DEFAULT '',
        prompted_at TEXT NOT NULL,
        handled_by_platform TEXT,
        handled_by_kind TEXT,
        handled_by_id TEXT,
        handled_by_scope_id TEXT,
        handled_at TEXT,
        accepted INTEGER,
        PRIMARY KEY (conversation_platform, conversation_kind, conversation_id)
    )
    """,
)
_MIGRATIONS = (SqliteMigration(1, _SCHEMA),)
MIGRATION_NAMESPACE = "team_resources"


class TeamResourceSubscriptionStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    def list_all(self) -> list[TeamResourceSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                _GROUP_SUBSCRIPTION_SELECT
                + " ORDER BY conversation_platform, conversation_kind, "
                "conversation_id, team_id"
            ).fetchall()
            return [_subscription_from_row(conn, row) for row in rows]

    def list_conversation(
        self,
        conversation: ConversationRef,
    ) -> list[TeamResourceSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                _GROUP_SUBSCRIPTION_SELECT
                + """
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ?
                ORDER BY team_id
                """,
                _conversation_values(conversation),
            ).fetchall()
            return [_subscription_from_row(conn, row) for row in rows]

    def upsert(self, update: TeamResourceSubscriptionUpdate) -> None:
        conversation_values = _conversation_values(update.conversation)
        operator_values = _actor_values(update.operator)
        now = _now_text()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO team_resource_subscriptions (
                    conversation_platform, conversation_kind, conversation_id,
                    team_id, team_name, threshold,
                    created_by_platform, created_by_kind, created_by_id,
                    created_by_scope_id, updated_by_platform, updated_by_kind,
                    updated_by_id, updated_by_scope_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    conversation_platform, conversation_kind, conversation_id, team_id
                ) DO UPDATE SET
                    team_name = excluded.team_name,
                    threshold = excluded.threshold,
                    updated_by_platform = excluded.updated_by_platform,
                    updated_by_kind = excluded.updated_by_kind,
                    updated_by_id = excluded.updated_by_id,
                    updated_by_scope_id = excluded.updated_by_scope_id,
                    updated_at = excluded.updated_at
                """,
                (
                    *conversation_values,
                    update.team_id,
                    update.team_name.strip(),
                    update.threshold,
                    *operator_values,
                    *operator_values,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                DELETE FROM team_resource_subscription_mentions
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND team_id = ?
                """,
                (*conversation_values, update.team_id),
            )
            _insert_mentions(
                conn,
                update.conversation,
                update.team_id,
                update.mention_actors,
            )

    def list_all_private(self) -> list[TeamResourcePrivateSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT actor_platform, actor_kind, actor_id, actor_scope_id,
                       team_id, team_name, threshold, created_at, updated_at
                FROM team_resource_private_subscriptions
                ORDER BY actor_platform, actor_kind, actor_id, actor_scope_id, team_id
                """
            ).fetchall()
        return [_private_subscription_from_row(row) for row in rows]

    def list_actor(self, actor: ActorRef) -> list[TeamResourcePrivateSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT actor_platform, actor_kind, actor_id, actor_scope_id,
                       team_id, team_name, threshold, created_at, updated_at
                FROM team_resource_private_subscriptions
                WHERE actor_platform = ? AND actor_kind = ? AND actor_id = ?
                  AND actor_scope_id = ?
                ORDER BY team_id
                """,
                _actor_values(actor),
            ).fetchall()
        return [_private_subscription_from_row(row) for row in rows]

    def upsert_private(self, update: TeamResourcePrivateSubscriptionUpdate) -> None:
        now = _now_text()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO team_resource_private_subscriptions (
                    actor_platform, actor_kind, actor_id, actor_scope_id,
                    team_id, team_name, threshold, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    actor_platform, actor_kind, actor_id, actor_scope_id, team_id
                ) DO UPDATE SET
                    team_name = excluded.team_name,
                    threshold = excluded.threshold,
                    updated_at = excluded.updated_at
                """,
                (
                    *_actor_values(update.actor),
                    update.team_id,
                    update.team_name.strip(),
                    update.threshold,
                    now,
                    now,
                ),
            )

    def has_prompted_conversation(self, conversation: ConversationRef) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM team_resource_subscription_prompts
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ?
                """,
                _conversation_values(conversation),
            ).fetchone()
        return row is not None

    def get_pending_prompt(
        self,
        conversation: ConversationRef,
    ) -> TeamResourceSubscriptionPrompt | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT conversation_platform, conversation_kind, conversation_id,
                       team_id, team_name, prompted_by_platform, prompted_by_kind,
                       prompted_by_id, prompted_by_scope_id, prompted_at,
                       handled_by_platform, handled_by_kind, handled_by_id,
                       handled_by_scope_id, handled_at, accepted
                FROM team_resource_subscription_prompts
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND handled_at IS NULL
                """,
                _conversation_values(conversation),
            ).fetchone()
        return _prompt_from_row(row) if row is not None else None

    def mark_conversation_prompted(
        self,
        *,
        conversation: ConversationRef,
        team_id: int,
        team_name: str,
        prompted_by: ActorRef,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO team_resource_subscription_prompts (
                    conversation_platform, conversation_kind, conversation_id,
                    team_id, team_name, prompted_by_platform, prompted_by_kind,
                    prompted_by_id, prompted_by_scope_id, prompted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    *_conversation_values(conversation),
                    team_id,
                    team_name.strip(),
                    *_actor_values(prompted_by),
                    _now_text(),
                ),
            )

    def mark_prompt_handled(
        self,
        *,
        conversation: ConversationRef,
        handled_by: ActorRef,
        accepted: bool,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE team_resource_subscription_prompts
                SET handled_by_platform = ?, handled_by_kind = ?, handled_by_id = ?,
                    handled_by_scope_id = ?, handled_at = ?, accepted = ?
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND handled_at IS NULL
                """,
                (
                    *_actor_values(handled_by),
                    _now_text(),
                    int(accepted),
                    *_conversation_values(conversation),
                ),
            )

    def update_team_name(
        self,
        *,
        conversation: ConversationRef,
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
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND team_id = ?
                """,
                (
                    team_name.strip(),
                    _now_text(),
                    *_conversation_values(conversation),
                    team_id,
                ),
            )

    def delete(self, *, conversation: ConversationRef, team_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM team_resource_subscriptions
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND team_id = ?
                """,
                (*_conversation_values(conversation), team_id),
            )
            conn.execute(
                """
                DELETE FROM team_resource_subscription_mentions
                WHERE conversation_platform = ? AND conversation_kind = ?
                  AND conversation_id = ? AND team_id = ?
                """,
                (*_conversation_values(conversation), team_id),
            )
            return cursor.rowcount > 0

    def update_private_team_name(
        self,
        *,
        actor: ActorRef,
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
                WHERE actor_platform = ? AND actor_kind = ? AND actor_id = ?
                  AND actor_scope_id = ? AND team_id = ?
                """,
                (
                    team_name.strip(),
                    _now_text(),
                    *_actor_values(actor),
                    team_id,
                ),
            )

    def delete_private(self, *, actor: ActorRef, team_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM team_resource_private_subscriptions
                WHERE actor_platform = ? AND actor_kind = ? AND actor_id = ?
                  AND actor_scope_id = ? AND team_id = ?
                """,
                (*_actor_values(actor), team_id),
            )
            return cursor.rowcount > 0

    def _connect(self):
        return self._database.connect()


_GROUP_SUBSCRIPTION_SELECT = """
    SELECT conversation_platform, conversation_kind, conversation_id,
           team_id, team_name, threshold,
           created_by_platform, created_by_kind, created_by_id,
           created_by_scope_id, updated_by_platform, updated_by_kind,
           updated_by_id, updated_by_scope_id, created_at, updated_at
    FROM team_resource_subscriptions
"""


def _subscription_from_row(
    connection: Any,
    row: tuple[Any, ...],
) -> TeamResourceSubscription:
    conversation = ConversationIdentityColumns(*row[:3]).to_conversation()
    created_by = ActorIdentityColumns(*row[6:10]).to_actor()
    updated_by = ActorIdentityColumns(*row[10:14]).to_actor()
    return TeamResourceSubscription(
        conversation=conversation,
        team_id=int(row[3]),
        team_name=str(row[4] or ""),
        threshold=int(row[5]),
        mention_actors=_mention_actors(connection, conversation, int(row[3])),
        created_by=created_by,
        updated_by=updated_by,
        created_at=str(row[14]),
        updated_at=str(row[15]),
    )


def _private_subscription_from_row(
    row: tuple[Any, ...],
) -> TeamResourcePrivateSubscription:
    return TeamResourcePrivateSubscription(
        actor=ActorIdentityColumns(*row[:4]).to_actor(),
        team_id=int(row[4]),
        team_name=str(row[5] or ""),
        threshold=int(row[6]),
        created_at=str(row[7]),
        updated_at=str(row[8]),
    )


def _prompt_from_row(row: tuple[Any, ...]) -> TeamResourceSubscriptionPrompt:
    handled_by = _optional_actor(row[10:14])
    return TeamResourceSubscriptionPrompt(
        conversation=ConversationIdentityColumns(*row[:3]).to_conversation(),
        team_id=int(row[3]),
        team_name=str(row[4] or ""),
        prompted_by=ActorIdentityColumns(*row[5:9]).to_actor(),
        prompted_at=str(row[9]),
        handled_by=handled_by,
        handled_at=None if row[14] is None else str(row[14]),
        accepted=None if row[15] is None else bool(row[15]),
    )


def _insert_mentions(
    connection: Any,
    conversation: ConversationRef,
    team_id: int,
    actors: tuple[ActorRef, ...],
) -> None:
    values = [
        (
            *_conversation_values(conversation),
            team_id,
            *_actor_values(actor),
            position,
        )
        for position, actor in enumerate(dict.fromkeys(actors))
    ]
    if values:
        connection.executemany(
            """
            INSERT INTO team_resource_subscription_mentions (
                conversation_platform, conversation_kind, conversation_id, team_id,
                actor_platform, actor_kind, actor_id, actor_scope_id, position
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )


def _mention_actors(
    connection: Any,
    conversation: ConversationRef,
    team_id: int,
) -> tuple[ActorRef, ...]:
    rows = connection.execute(
        """
        SELECT actor_platform, actor_kind, actor_id, actor_scope_id
        FROM team_resource_subscription_mentions
        WHERE conversation_platform = ? AND conversation_kind = ?
          AND conversation_id = ? AND team_id = ?
        ORDER BY position
        """,
        (*_conversation_values(conversation), team_id),
    ).fetchall()
    return tuple(ActorIdentityColumns(*row).to_actor() for row in rows)


def _conversation_values(conversation: ConversationRef) -> tuple[str, str, str]:
    return ConversationIdentityColumns.from_conversation(conversation).values()


def _actor_values(actor: ActorRef) -> tuple[str, str, str, str]:
    return ActorIdentityColumns.from_actor(actor).values()


def _optional_actor(values: tuple[Any, ...]) -> ActorRef | None:
    if all(value is None for value in values):
        return None
    return ActorIdentityColumns(*values).to_actor()


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
