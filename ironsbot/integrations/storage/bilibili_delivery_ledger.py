# SPDX-License-Identifier: MIT
"""Durable stage claims: failures are terminal, only unattempted work resumes."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from ironsbot.core.outbound import DeliveryFailureKind
from ironsbot.integrations.storage.sqlite import SqliteDatabase
from ironsbot.services.bilibili.parser import dynamic_content, dynamic_image_urls

if TYPE_CHECKING:
    import sqlite3
    from contextlib import AbstractContextManager
    from pathlib import Path

    from ironsbot.core.outbound import SendResult
    from ironsbot.core.platform import ConversationRef
    from ironsbot.services.bilibili.target_models import BiliPushTargets

RETENTION_SECONDS = 86400


class SqliteDynamicDeliveryLedger:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS stages (
                    dynamic_id TEXT NOT NULL, target TEXT NOT NULL, stage TEXT NOT NULL,
                    state TEXT NOT NULL, result TEXT,
                    PRIMARY KEY(dynamic_id, target, stage));
                CREATE TABLE IF NOT EXISTS notifications (dynamic_id TEXT PRIMARY KEY);
            """)

    def _connect(self) -> AbstractContextManager[sqlite3.Connection]:
        return SqliteDatabase(self.path).connect()

    @staticmethod
    def _target(target: ConversationRef) -> str:
        return json.dumps(asdict(target), sort_keys=True)

    def prepare(
        self,
        item: dict[str, Any],
        pub_ts: int,
        uid: int,
        targets: BiliPushTargets,
        categories: tuple[str, ...],
    ) -> bool:
        dynamic_id = str(item["id_str"])
        payload = json.dumps(
            {
                "item": item,
                "pub_ts": pub_ts,
                "uid": uid,
                "targets": asdict(targets),
                "categories": categories,
            }
        )
        with self._connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?)",
                (dynamic_id, time.time(), payload),
            )
            if cursor.rowcount == 0:
                return False
            for name, conversations in asdict(targets).items():
                phases = ["link"]
                if name.startswith("full"):
                    if dynamic_content(item).strip():
                        phases.append("text")
                    if dynamic_image_urls(item):
                        phases.append("image")
                for target in conversations:
                    for phase in phases:
                        db.execute(
                            "INSERT OR IGNORE INTO stages "
                            "VALUES (?, ?, ?, 'pending', NULL)",
                            (dynamic_id, json.dumps(target, sort_keys=True), phase),
                        )
        return True

    def recover(self) -> None:
        with self._connect() as db:
            db.execute("UPDATE stages SET state='uncertain' WHERE state='sending'")
            db.execute(
                "UPDATE stages SET state='expired' "
                "WHERE state='pending' AND dynamic_id IN "
                "(SELECT id FROM deliveries WHERE created < ? "
                "OR json_extract(payload, '$.pub_ts') < ?)",
                (time.time() - RETENTION_SECONDS, time.time() - RETENTION_SECONDS),
            )

    def pending(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT payload FROM deliveries WHERE created >= ? AND id IN "
                    "(SELECT dynamic_id FROM stages WHERE state='pending') "
                    "ORDER BY created",
                    (time.time() - RETENTION_SECONDS,),
                )
            ]

    def claim_notification(self, dynamic_id: str) -> bool:
        with self._connect() as db:
            return (
                db.execute(
                    "INSERT OR IGNORE INTO notifications VALUES (?)",
                    (dynamic_id,),
                ).rowcount
                == 1
            )

    def claim(self, dynamic_id: str, target: ConversationRef, stage: str) -> bool:
        with self._connect() as db:
            return (
                db.execute(
                    "UPDATE stages SET state='sending' WHERE dynamic_id=? "
                    "AND target=? AND stage=? AND state='pending'",
                    (dynamic_id, self._target(target), stage),
                ).rowcount
                == 1
            )

    def unattempted(self, dynamic_id: str, target: ConversationRef, stage: str) -> bool:
        with self._connect() as db:
            return (
                db.execute(
                    "SELECT 1 FROM stages WHERE dynamic_id=? AND target=? "
                    "AND stage=? AND state='pending'",
                    (dynamic_id, self._target(target), stage),
                ).fetchone()
                is not None
            )

    def finish(
        self, dynamic_id: str, target: ConversationRef, stage: str, result: SendResult
    ) -> None:
        state = "success" if result.delivered else "failed"
        if not result.attempted:
            state = (
                "skipped"
                if result.failure_kind is DeliveryFailureKind.PERMANENT
                else "pending"
            )
        elif result.error_code == "bot_unavailable":
            state = "pending"
        elif (
            result.failure_kind is not None and result.failure_kind.value == "uncertain"
        ):
            state = "uncertain"
        with self._connect() as db:
            db.execute(
                "UPDATE stages SET state=?, result=? WHERE dynamic_id=? AND target=? "
                "AND stage=? AND state='sending'",
                (
                    state,
                    json.dumps(asdict(result)),
                    dynamic_id,
                    self._target(target),
                    stage,
                ),
            )

    def skip_remaining(self, dynamic_id: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE stages SET state='skipped' "
                "WHERE dynamic_id=? AND state='pending' "
                "AND result IS NULL",
                (dynamic_id,),
            )
