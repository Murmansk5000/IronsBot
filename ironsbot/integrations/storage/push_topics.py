# SPDX-License-Identifier: MIT
"""Persistent opt-in topics and per-target delivery claims."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, cast

from ironsbot.core.platform import ConversationKind, ConversationRef, Platform
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration
from ironsbot.services.messaging.topic_models import (
    PushTopic,
    TopicDeliveryRecord,
    TopicDeliveryStatus,
)

_SCHEMA = (
    "CREATE TABLE push_topics (key TEXT PRIMARY KEY, name TEXT NOT NULL, "
    "enabled INTEGER NOT NULL, code_registered INTEGER NOT NULL)",
    "CREATE TABLE push_topic_subscribers (topic TEXT NOT NULL, target TEXT NOT NULL, "
    "PRIMARY KEY(topic,target))",
    "CREATE TABLE push_topic_deliveries (id INTEGER PRIMARY KEY, topic TEXT NOT NULL, "
    "target TEXT NOT NULL, dedup_key TEXT, status TEXT NOT NULL, "
    "created_at REAL NOT NULL)",
    "CREATE INDEX push_topic_delivery_lookup ON push_topic_deliveries "
    "(topic,target,dedup_key,created_at)",
)

if TYPE_CHECKING:
    from pathlib import Path


def _encode(target: ConversationRef) -> str:
    return json.dumps(
        [target.platform.value, target.kind, target.id, target.account_id],
        separators=(",", ":"),
    )


def _decode(raw: str) -> ConversationRef:
    values = cast("list[str | None]", json.loads(raw))
    return ConversationRef(
        Platform(values[0]),
        cast("ConversationKind", values[1]),
        cast("str", values[2]),
        values[3],
    )


class SqlitePushTopicStore:
    def __init__(self, path: str | Path) -> None:
        self.database = SqliteDatabase(
            path,
            migrations=(SqliteMigration(1, _SCHEMA),),
            migration_namespace="push_topics",
            row_factory=sqlite3.Row,
        )

    def topics(self) -> tuple[PushTopic, ...]:
        with self.database.connect() as db:
            return tuple(
                PushTopic(
                    row["key"],
                    row["name"],
                    bool(row["enabled"]),
                    bool(row["code_registered"]),
                )
                for row in db.execute("SELECT * FROM push_topics ORDER BY key")
            )

    def create(self, topic: PushTopic) -> None:
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO push_topics VALUES (?,?,?,?)",
                (
                    topic.key,
                    topic.name,
                    topic.enabled,
                    topic.code_registered,
                ),
            )

    def set_enabled(self, key: str, *, enabled: bool) -> None:
        with self.database.connect() as db:
            db.execute("UPDATE push_topics SET enabled=? WHERE key=?", (enabled, key))

    def delete(self, key: str) -> None:
        with self.database.connect() as db:
            db.execute(
                "DELETE FROM push_topics WHERE key=? AND code_registered=0", (key,)
            )
            db.execute("DELETE FROM push_topic_subscribers WHERE topic=?", (key,))
            db.execute("DELETE FROM push_topic_deliveries WHERE topic=?", (key,))

    def subscribe(self, key: str, target: ConversationRef) -> None:
        with self.database.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO push_topic_subscribers VALUES (?,?)",
                (key, _encode(target)),
            )

    def subscribers(self, key: str) -> tuple[ConversationRef, ...]:
        with self.database.connect() as db:
            return tuple(
                _decode(row[0])
                for row in db.execute(
                    "SELECT target FROM push_topic_subscribers "
                    "WHERE topic=? ORDER BY target",
                    (key,),
                )
            )

    def claim(
        self, key: str, target: ConversationRef, dedup_key: str | None, now: float
    ) -> int | None:
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                dedup_key is not None
                and db.execute(
                    "SELECT 1 FROM push_topic_deliveries WHERE topic=? AND target=? "
                    "AND dedup_key=? AND created_at>? "
                    "AND status IN ('pending','delivered','uncertain') LIMIT 1",
                    (key, _encode(target), dedup_key, now - 3600),
                ).fetchone()
            ):
                return None
            cursor = db.execute(
                "INSERT INTO push_topic_deliveries "
                "(topic,target,dedup_key,status,created_at) VALUES (?,?,?,'pending',?)",
                (key, _encode(target), dedup_key, now),
            )
            return cursor.lastrowid

    def finish(self, record_id: int, status: TopicDeliveryStatus) -> None:
        with self.database.connect() as db:
            db.execute(
                "UPDATE push_topic_deliveries SET status=? WHERE id=?",
                (status, record_id),
            )

    def prune(self, key: str, now: float) -> None:
        # Recent claims survive history trimming: 500 displayed rows must not
        # weaken the independent one-hour idempotency window.
        with self.database.connect() as db:
            db.execute(
                "DELETE FROM push_topic_deliveries WHERE topic=? AND created_at<=? "
                "AND id NOT IN (SELECT id FROM push_topic_deliveries WHERE topic=? "
                "ORDER BY id DESC LIMIT 500)",
                (key, now - 3600, key),
            )

    def history(self, key: str) -> tuple[TopicDeliveryRecord, ...]:
        with self.database.connect() as db:
            return tuple(
                TopicDeliveryRecord(
                    key,
                    _decode(row["target"]),
                    cast("TopicDeliveryStatus", row["status"]),
                    row["created_at"],
                )
                for row in db.execute(
                    "SELECT * FROM push_topic_deliveries WHERE topic=? "
                    "ORDER BY id DESC LIMIT 500",
                    (key,),
                )
            )
