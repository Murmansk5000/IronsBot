# SPDX-License-Identifier: MIT
"""Durable per-destination FIFO turns shared by discovery and recovery."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from ironsbot.core.delivery_attempt import delivery_execution
from ironsbot.core.outbound import DeliveryFailureKind, SendResult
from ironsbot.core.platform import reference_digest
from ironsbot.integrations.storage.bilibili_media_preparation import (
    MediaPreparationStore,
)

if TYPE_CHECKING:
    import sqlite3

    from ironsbot.core.platform import ConversationRef

_RETENTION = 86400
_CLOSED = frozenset({"done", "expired", "released_uncertain"})
_LOGGER = logging.getLogger(__name__)


def initialize_queue(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS conversation_queue (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            dynamic_id TEXT NOT NULL, target TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'queued',
            UNIQUE(dynamic_id,target));
        CREATE INDEX IF NOT EXISTS conversation_queue_head
            ON conversation_queue(target,sequence,state);
    """)
    db.execute(
        "INSERT OR IGNORE INTO conversation_queue(dynamic_id,target) "
        "SELECT s.dynamic_id,s.target FROM stages s JOIN deliveries d "
        "ON d.id=s.dynamic_id GROUP BY s.dynamic_id,s.target "
        "ORDER BY d.created,json_extract(d.payload,'$.pub_ts'),d.id,s.target"
    )


class ConversationQueueStore(MediaPreparationStore):
    def queue_wait_account(self, dynamic_id: str, target: ConversationRef) -> None:
        raw = self._target(target)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for stage, attempts, previous in db.execute(
                "SELECT stage,attempts,result FROM stages "
                "WHERE dynamic_id=? AND target=? "
                "AND state IN ('pending','retry','waiting') ORDER BY "
                "CASE stage WHEN 'link' THEN 0 WHEN 'text' THEN 1 WHEN 'image' THEN 2 "
                "ELSE 3 END,CAST(SUBSTR(stage,7) AS INTEGER) LIMIT 1",
                (dynamic_id, raw),
            ).fetchall():
                result = SendResult(
                    delivered=False,
                    attempted=False,
                    error_code="account_temporarily_unavailable",
                    failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
                    attempt_count=attempts,
                )
                db.execute(
                    "UPDATE stages SET state='waiting',result=?,"
                    "started_at=CASE WHEN attempts=0 THEN 0 ELSE started_at END,"
                    "deadline_at=CASE WHEN attempts=0 THEN 0 ELSE deadline_at END "
                    "WHERE dynamic_id=? AND target=? AND stage=?",
                    (
                        previous
                        if stage == "image"
                        and previous
                        and str(json.loads(previous).get("error_code", "")).startswith(
                            "media_prepare:"
                        )
                        else json.dumps(asdict(result)),
                        dynamic_id,
                        raw,
                        stage,
                    ),
                )
            db.execute(
                "UPDATE conversation_queue SET state='waiting' "
                "WHERE dynamic_id=? AND target=? AND state='running'",
                (dynamic_id, raw),
            )

    def queue_entry(self, dynamic_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM deliveries WHERE id=?", (dynamic_id,)
            ).fetchone()
        if row is None:
            message = "Delivery is not registered"
            raise ValueError(message)
        return json.loads(row[0])

    def _queue_refresh(self, db: sqlite3.Connection) -> None:
        now = self._now()
        rows = db.execute(
            "SELECT q.dynamic_id,q.target,q.state,d.created,d.payload,"
            "EXISTS(SELECT 1 FROM delivery_executions e "
            "WHERE e.id=q.dynamic_id AND e.expires>?) "
            "FROM conversation_queue q JOIN deliveries d ON d.id=q.dynamic_id "
            "WHERE q.state NOT IN ('done','expired','released_uncertain')",
            (now,),
        ).fetchall()
        for dynamic_id, target, state, created, payload, owned in rows:
            if owned and state in {"running", "blocked"}:
                continue
            stages = {
                row[0]
                for row in db.execute(
                    "SELECT state FROM stages WHERE dynamic_id=? AND target=?",
                    (dynamic_id, target),
                )
            }
            expired = min(created, json.loads(payload)["pub_ts"]) + _RETENTION < now
            if expired and not (owned and "sending" in stages):
                updated = "expired"
                db.execute(
                    "UPDATE stages SET state='expired' WHERE dynamic_id=? AND target=? "
                    "AND state IN ('pending','retry','waiting')",
                    (dynamic_id, target),
                )
                if not owned:
                    db.execute(
                        "UPDATE stages SET state='uncertain' "
                        "WHERE dynamic_id=? AND target=? "
                        "AND state='sending'",
                        (dynamic_id, target),
                    )
            elif "sending" in stages and not owned:
                db.execute(
                    "UPDATE stages SET state='uncertain' WHERE dynamic_id=? "
                    "AND target=? AND state='sending'",
                    (dynamic_id, target),
                )
                updated = "released_uncertain"
            elif "uncertain" in stages:
                updated = "blocked" if owned else "released_uncertain"
            elif not stages.intersection({"pending", "retry", "waiting", "sending"}):
                updated = "done"
            elif state == "running" and not owned:
                updated = "waiting" if "waiting" in stages else "queued"
            else:
                continue
            self._block_uncertain_following(db, dynamic_id, target)
            db.execute(
                "UPDATE conversation_queue SET state=? WHERE dynamic_id=? AND target=?",
                (updated, dynamic_id, target),
            )
            if updated != state:
                _LOGGER.info(
                    "Bilibili conversation queue reconciled: "
                    "dynamic=%s target=%s state=%s",
                    dynamic_id,
                    reference_digest(target),
                    updated,
                )

    def _block_uncertain_following(
        self, db: sqlite3.Connection, dynamic_id: str, target: str
    ) -> None:
        for (stage,) in db.execute(
            "SELECT stage FROM stages WHERE dynamic_id=? AND target=? "
            "AND state='uncertain'",
            (dynamic_id, target),
        ).fetchall():
            self._block_following_db(db, dynamic_id, target, stage)

    def queue_claim(
        self, dynamic_id: str, targets: tuple[ConversationRef, ...]
    ) -> set[ConversationRef]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._queue_refresh(db)
            ownership = delivery_execution.get()
            if ownership is None or ownership[0] != dynamic_id:
                return set()
            claimed = set()
            for target in targets:
                if db.execute(
                    "UPDATE conversation_queue SET state='running' "
                    "WHERE dynamic_id=? AND target=? AND state='queued' AND sequence="
                    "(SELECT MIN(sequence) FROM conversation_queue WHERE target=? "
                    "AND state NOT IN ('done','expired','released_uncertain')) "
                    "AND EXISTS("
                    "SELECT 1 FROM delivery_executions "
                    "WHERE id=? AND owner=? AND expires>?)",
                    (
                        dynamic_id,
                        self._target(target),
                        self._target(target),
                        *ownership,
                        self._now(),
                    ),
                ).rowcount:
                    claimed.add(target)
            return claimed

    def queue_wake(self, dynamic_id: str, targets: tuple[ConversationRef, ...]) -> None:
        with self._connect() as db:
            for target in targets:
                db.execute(
                    "UPDATE stages SET state='pending',result=NULL "
                    "WHERE dynamic_id=? AND target=? AND state='waiting' "
                    "AND attempts=0 AND json_extract(result,'$.error_code')="
                    "'account_temporarily_unavailable'",
                    (dynamic_id, self._target(target)),
                )
                db.execute(
                    "UPDATE stages SET state='retry' "
                    "WHERE dynamic_id=? AND target=? AND stage='image' "
                    "AND state='waiting' "
                    "AND json_extract(result,'$.error_code') LIKE 'media_prepare:%'",
                    (dynamic_id, self._target(target)),
                )
                db.execute(
                    "UPDATE conversation_queue SET state='queued' "
                    "WHERE dynamic_id=? AND target=? AND state='waiting'",
                    (dynamic_id, self._target(target)),
                )

    def queue_settle(
        self, dynamic_id: str, target: ConversationRef, *, final: bool = False
    ) -> bool:
        raw = self._target(target)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ownership = delivery_execution.get()
            if (
                ownership is None
                or ownership[0] != dynamic_id
                or db.execute(
                    "SELECT 1 FROM delivery_executions "
                    "WHERE id=? AND owner=? AND expires>?",
                    (*ownership, self._now()),
                ).fetchone()
                is None
            ):
                return False
            row = db.execute(
                "SELECT state FROM conversation_queue WHERE dynamic_id=? AND target=?",
                (dynamic_id, raw),
            ).fetchone()
            if row is None or row[0] != "running":
                return False
            states = {
                row[0]
                for row in db.execute(
                    "SELECT state FROM stages WHERE dynamic_id=? AND target=?",
                    (dynamic_id, raw),
                )
            }
            if states.intersection({"sending", "uncertain"}):
                state = "blocked"
            elif "waiting" in states:
                state = "waiting"
            elif "retry" in states:
                state = "waiting" if final else "running"
            elif final and "pending" in states:
                state = "waiting"
            else:
                db.execute(
                    "UPDATE stages SET state='skipped' WHERE dynamic_id=? AND target=? "
                    "AND state='pending' AND result IS NULL",
                    (dynamic_id, raw),
                )
                state = "done"
            db.execute(
                "UPDATE conversation_queue SET state=? WHERE dynamic_id=? AND target=?",
                (state, dynamic_id, raw),
            )
            if state != "running":
                _LOGGER.info(
                    "Bilibili conversation turn ended: dynamic=%s target=%s state=%s",
                    dynamic_id,
                    reference_digest(target.id),
                    state,
                )
            return state in _CLOSED

    def queue_ready(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._queue_refresh(db)
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT d.payload FROM deliveries d WHERE EXISTS("
                    "SELECT 1 FROM conversation_queue q WHERE q.dynamic_id=d.id "
                    "AND q.state='queued' AND q.sequence=(SELECT MIN(p.sequence) "
                    "FROM conversation_queue p WHERE p.target=q.target "
                    "AND p.state NOT IN ('done','expired','released_uncertain'))) "
                    "AND NOT EXISTS(SELECT 1 FROM delivery_executions e "
                    "WHERE e.id=d.id AND e.expires>?) ORDER BY d.created,d.id",
                    (self._now(),),
                )
            ]
