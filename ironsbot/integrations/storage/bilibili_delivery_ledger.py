# SPDX-License-Identifier: MIT
"""Durable claims and bounded retries, with conservative legacy recovery."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ironsbot.core.outbound import DeliveryFailureKind, ExecutionIdentity, SendResult
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.storage.bilibili_media_manifest import (
    decode_media,
    encode_media,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase
from ironsbot.services.bilibili.delivery_rounds import BILI_RETRY_DELAYS
from ironsbot.services.bilibili.parser import dynamic_content, dynamic_image_urls

if TYPE_CHECKING:
    import sqlite3
    from contextlib import AbstractContextManager

    from ironsbot.core.outbound import OutboundMessage
    from ironsbot.services.bilibili.target_models import BiliPushTargets

RETENTION_SECONDS = 86400
RETRY_DELAYS = BILI_RETRY_DELAYS
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1


class SqliteDynamicDeliveryLedger:
    def __init__(self, path: Path, *, media_root: Path | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        from ironsbot.runtime.cache_paths import CachePaths

        self.media_root = (
            media_root or CachePaths(Path("cache")).assets_dir() / "bilibili"
        )
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS stages (
                    dynamic_id TEXT NOT NULL, target TEXT NOT NULL, stage TEXT NOT NULL,
                    state TEXT NOT NULL, result TEXT,
                    PRIMARY KEY(dynamic_id, target, stage));
                CREATE TABLE IF NOT EXISTS notifications (dynamic_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS media_manifests (
                    dynamic_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS delivery_rounds (
                    dynamic_id TEXT PRIMARY KEY, count INTEGER NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 1);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(stages)")}
            for name, definition in (
                ("attempts", "INTEGER NOT NULL DEFAULT 0"),
                ("next_retry", "REAL NOT NULL DEFAULT 0"),
                ("retry_enabled", "INTEGER NOT NULL DEFAULT 0"),
                ("last_round", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE stages ADD COLUMN {name} {definition}")

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
                            "(dynamic_id,target,stage,state,result,retry_enabled) "
                            "VALUES (?, ?, ?, 'pending', NULL, 1)",
                            (dynamic_id, json.dumps(target, sort_keys=True), phase),
                        )
        return True

    def recover(self) -> None:
        with self._connect() as db:
            db.execute("UPDATE stages SET state='uncertain' WHERE state='sending'")
            db.execute(
                "UPDATE stages SET state='expired' "
                "WHERE state IN ('pending','retry') AND dynamic_id IN "
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
                    "(SELECT dynamic_id FROM stages "
                    "WHERE state IN ('pending','retry') OR "
                    "(retry_enabled=1 AND state IN ('failed','uncertain') "
                    "AND dynamic_id NOT IN (SELECT dynamic_id FROM notifications))) "
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
                    "UPDATE stages SET state='sending', attempts=attempts+1, "
                    "last_round=COALESCE((SELECT count FROM delivery_rounds "
                    "WHERE dynamic_id=stages.dynamic_id),0) "
                    "WHERE dynamic_id=? "
                    "AND target=? AND stage=? AND state IN ('pending','retry') "
                    "AND next_retry<=? AND attempts<4 AND dynamic_id IN "
                    "(SELECT id FROM deliveries WHERE created>=? "
                    "AND json_extract(payload,'$.pub_ts')>=?) "
                    "AND (COALESCE((SELECT count FROM delivery_rounds "
                    "WHERE dynamic_id=stages.dynamic_id),0)=0 OR "
                    "last_round < (SELECT count FROM delivery_rounds "
                    "WHERE dynamic_id=stages.dynamic_id)) "
                    "AND (stage NOT LIKE 'image:%' OR NOT EXISTS "
                    "(SELECT 1 FROM stages AS previous WHERE "
                    "previous.dynamic_id=stages.dynamic_id "
                    "AND previous.target=stages.target "
                    "AND previous.stage LIKE 'image:%' "
                    "AND CAST(substr(previous.stage,7) AS INTEGER) "
                    "< CAST(substr(stages.stage,7) AS INTEGER) "
                    "AND previous.state!='success'))",
                    (
                        dynamic_id,
                        self._target(target),
                        stage,
                        time.time(),
                        time.time() - RETENTION_SECONDS,
                        time.time() - RETENTION_SECONDS,
                    ),
                ).rowcount
                == 1
            )

    def unattempted(self, dynamic_id: str, target: ConversationRef, stage: str) -> bool:
        with self._connect() as db:
            return (
                db.execute(
                    "SELECT 1 FROM stages WHERE dynamic_id=? AND target=? "
                    "AND (stage=? OR (?='image' AND stage LIKE 'image:%')) "
                    "AND state IN ('pending','retry')",
                    (dynamic_id, self._target(target), stage, stage),
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
            row = db.execute(
                "SELECT attempts,retry_enabled FROM stages WHERE dynamic_id=? "
                "AND target=? AND stage=? AND state='sending'",
                (dynamic_id, self._target(target), stage),
            ).fetchone()
            if row is None:
                return
            next_retry = 0.0
            round_row = db.execute(
                "SELECT count FROM delivery_rounds WHERE dynamic_id=?", (dynamic_id,)
            ).fetchone()
            round_number = round_row[0] if round_row else row[0]
            if (
                result.attempted
                and result.failure_kind is DeliveryFailureKind.RETRYABLE
                and row[1]
                and row[0] < MAX_ATTEMPTS
                and round_number < MAX_ATTEMPTS
            ):
                state = "retry"
                next_retry = time.time() + RETRY_DELAYS[max(0, round_number - 1)]
            db.execute(
                "UPDATE stages SET state=?, result=?, next_retry=? "
                "WHERE dynamic_id=? AND target=? "
                "AND stage=? AND state='sending'",
                (
                    state,
                    json.dumps(asdict(result)),
                    next_retry,
                    dynamic_id,
                    self._target(target),
                    stage,
                ),
            )
            if not result.attempted or result.error_code == "bot_unavailable":
                db.execute(
                    "UPDATE stages SET attempts=MAX(0,attempts-1) "
                    "WHERE dynamic_id=? AND target=? AND stage=?",
                    (dynamic_id, self._target(target), stage),
                )

    def round_count(self, dynamic_id: str) -> int:
        with self._connect() as db:
            row = db.execute(
                "SELECT count FROM delivery_rounds WHERE dynamic_id=?", (dynamic_id,)
            ).fetchone()
            return row[0] if row else 0

    def state_counts(self, dynamic_id: str) -> dict[str, int]:
        with self._connect() as db:
            return dict(
                db.execute(
                    "SELECT state,COUNT(*) FROM stages WHERE dynamic_id=? "
                    "AND state!='delegated' GROUP BY state",
                    (dynamic_id,),
                )
            )

    def completed_round_count(self, dynamic_id: str) -> int:
        with self._connect() as db:
            row = db.execute(
                "SELECT count,completed FROM delivery_rounds WHERE dynamic_id=?",
                (dynamic_id,),
            ).fetchone()
            return max(0, row[0] - (not row[1])) if row else 0

    def begin_round(self, dynamic_id: str) -> bool:
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO delivery_rounds (dynamic_id,count) VALUES (?,0)",
                (dynamic_id,),
            )
            row = db.execute(
                "SELECT completed FROM delivery_rounds WHERE dynamic_id=?",
                (dynamic_id,),
            ).fetchone()
            if row is not None and not row[0]:
                return True
            return (
                db.execute(
                    "UPDATE delivery_rounds SET count=count+1,completed=0 "
                    "WHERE dynamic_id=? AND count<4",
                    (dynamic_id,),
                ).rowcount
                == 1
            )

    def finish_round(self, dynamic_id: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE delivery_rounds SET completed=1 WHERE dynamic_id=?",
                (dynamic_id,),
            )

    def attempts(self, dynamic_id: str, target: ConversationRef, stage: str) -> int:
        with self._connect() as db:
            row = db.execute(
                "SELECT attempts FROM stages "
                "WHERE dynamic_id=? AND target=? AND stage=?",
                (dynamic_id, self._target(target), stage),
            ).fetchone()
            return row[0] if row else 0

    def retry_delay(self, dynamic_id: str) -> float | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT MAX(next_retry) FROM stages "
                "WHERE dynamic_id=? AND state='retry'",
                (dynamic_id,),
            ).fetchone()
            return (
                max(0.0, row[0] - time.time()) if row and row[0] is not None else None
            )

    def failures(
        self, dynamic_id: str
    ) -> list[tuple[ConversationRef, str, SendResult]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT target,stage,result,state FROM stages WHERE dynamic_id=? "
                "AND retry_enabled=1 "
                "AND state IN ('failed','uncertain','retry','blocked')",
                (dynamic_id,),
            ).fetchall()
        result = []
        for raw_target, stage, raw_result, state in rows:
            target = json.loads(raw_target)
            target["platform"] = Platform(target["platform"])
            data = (
                json.loads(raw_result)
                if raw_result
                else {
                    "delivered": False,
                    "error_code": "interrupted_send",
                    "failure_kind": "uncertain",
                }
            )
            if state == "blocked":
                data = {
                    "delivered": False,
                    "error_code": "preceding_image_failed",
                    "failure_kind": "permanent",
                    "attempt_count": 0,
                }
            if data.get("failure_kind"):
                data["failure_kind"] = DeliveryFailureKind(data["failure_kind"])
            if identity := data.get("execution_identity"):
                identity["platform"] = Platform(identity["platform"])
                data["execution_identity"] = ExecutionIdentity(**identity)
            result.append((ConversationRef(**target), stage, SendResult(**data)))
        return result

    def load_media(self, dynamic_id: str) -> tuple[bool, OutboundMessage | None]:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM media_manifests WHERE dynamic_id=?", (dynamic_id,)
            ).fetchone()
        return (True, decode_media(row[0], self.media_root)) if row else (False, None)

    def freeze_media(
        self, dynamic_id: str, message: OutboundMessage | None
    ) -> OutboundMessage | None:
        found, previous = self.load_media(dynamic_id)
        if found:
            return previous
        payload = encode_media(message, self.media_root)
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO media_manifests VALUES (?,?)",
                (dynamic_id, payload),
            )
        return self.load_media(dynamic_id)[1]

    def image_units(self, dynamic_id: str, target: ConversationRef, count: int) -> None:
        with self._connect() as db:
            # Never expand an attempted legacy whole-image stage.
            row = db.execute(
                "SELECT state,result FROM stages "
                "WHERE dynamic_id=? AND target=? AND stage='image'",
                (dynamic_id, self._target(target)),
            ).fetchone()
            if row is None or row[0] != "pending" or row[1] is not None:
                return
            db.execute(
                "UPDATE stages SET state='delegated' "
                "WHERE dynamic_id=? AND target=? AND stage='image'",
                (dynamic_id, self._target(target)),
            )
            for index in range(count):
                db.execute(
                    "INSERT OR IGNORE INTO stages "
                    "(dynamic_id,target,stage,state,retry_enabled) "
                    "VALUES (?,?,?,'pending',1)",
                    (dynamic_id, self._target(target), f"image:{index + 1}"),
                )

    def skip_remaining(self, dynamic_id: str) -> bool:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "SELECT 1 FROM stages WHERE dynamic_id=? AND state='sending'",
                    (dynamic_id,),
                ).fetchone()
                is not None
            ):
                return False
            db.execute(
                "UPDATE stages SET state='blocked' WHERE dynamic_id=? "
                "AND stage LIKE 'image:%' AND state='pending' AND result IS NULL",
                (dynamic_id,),
            )
            db.execute(
                "UPDATE stages SET state='skipped' "
                "WHERE dynamic_id=? AND state='pending' "
                "AND result IS NULL",
                (dynamic_id,),
            )
            return True
