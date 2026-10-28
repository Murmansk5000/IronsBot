# SPDX-License-Identifier: MIT
"""Persistent execution ownership and bounded, ordered stage observations."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import TYPE_CHECKING

from ironsbot.core.outbound import DeliveryFailureKind, ExecutionIdentity, SendResult
from ironsbot.core.platform import Platform
from ironsbot.integrations.storage.sqlite import SqliteDatabase

if TYPE_CHECKING:
    import sqlite3
    from contextlib import AbstractContextManager
    from pathlib import Path

    from ironsbot.core.platform import ConversationRef

STAGE_SECONDS = 60.0
LEASE_SECONDS = 30.0
TERMINAL_STATES = frozenset({"success", "skipped", "failed", "expired", "delegated"})


def predecessors(stage: str) -> tuple[str, ...]:
    if stage == "link":
        return ()
    if stage == "text":
        return ("link",)
    if stage.startswith("image:"):
        return ("link", "text", *(f"image:{i}" for i in range(1, int(stage[6:]))))
    return ("link", "text")


class DeliveryLifecycleStore:
    path: Path

    def _now(self) -> float:
        return time.time()

    def _connect(self) -> AbstractContextManager[sqlite3.Connection]:
        return SqliteDatabase(self.path).connect()

    @staticmethod
    def _target(target: ConversationRef) -> str:
        return json.dumps(asdict(target), sort_keys=True)

    def acquire_execution(self, key: str, owner: str) -> bool:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT expires FROM delivery_executions WHERE id=?", (key,)
            ).fetchone()
            if previous is not None and previous[0] > self._now():
                return False
            if previous is not None:
                interrupted = db.execute(
                    "SELECT target,stage FROM stages "
                    "WHERE dynamic_id=? AND state='sending'",
                    (key,),
                ).fetchall()
                db.execute(
                    "UPDATE stages SET state='uncertain' "
                    "WHERE dynamic_id=? AND state='sending'",
                    (key,),
                )
                db.execute(
                    "UPDATE delivery_rounds SET completed=1 WHERE dynamic_id=?", (key,)
                )
                for target, stage in interrupted:
                    self._block_following_db(db, key, target, stage)
            db.execute(
                "INSERT INTO delivery_executions VALUES (?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "owner=excluded.owner,expires=excluded.expires",
                (key, owner, self._now() + LEASE_SECONDS),
            )
            return True

    def renew_execution(self, key: str, owner: str) -> bool:
        with self._connect() as db:
            return (
                db.execute(
                    "UPDATE delivery_executions SET expires=? WHERE id=? AND owner=?",
                    (self._now() + LEASE_SECONDS, key, owner),
                ).rowcount
                == 1
            )

    def release_execution(self, key: str, owner: str) -> None:
        with self._connect() as db:
            db.execute(
                "DELETE FROM delivery_executions WHERE id=? AND owner=?", (key, owner)
            )

    def stage_state(self, dynamic_id: str, target: ConversationRef, stage: str) -> str:
        with self._connect() as db:
            row = db.execute(
                "SELECT state FROM stages WHERE dynamic_id=? AND target=? AND stage=?",
                (dynamic_id, self._target(target), stage),
            ).fetchone()
        return str(row[0]) if row else "skipped"

    def stage_result(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> SendResult | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT result FROM stages WHERE dynamic_id=? AND target=? AND stage=?",
                (dynamic_id, self._target(target), stage),
            ).fetchone()
        if not row or not row[0]:
            return None
        data = json.loads(row[0])
        if data.get("failure_kind"):
            data["failure_kind"] = DeliveryFailureKind(data["failure_kind"])
        if identity := data.get("execution_identity"):
            identity["platform"] = Platform(identity["platform"])
            data["execution_identity"] = ExecutionIdentity(**identity)
        return SendResult(**data)

    def predecessors_done(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> bool:
        return all(
            self.stage_state(dynamic_id, target, previous) in TERMINAL_STATES
            for previous in predecessors(stage)
        )

    def start_stage(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> float:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE stages SET started_at=?,deadline_at=? "
                "WHERE dynamic_id=? AND target=? AND stage=? AND deadline_at=0 "
                "AND state IN ('pending','retry','waiting')",
                (
                    self._now(),
                    self._now() + STAGE_SECONDS,
                    dynamic_id,
                    self._target(target),
                    stage,
                ),
            )
            row = db.execute(
                "SELECT deadline_at FROM stages WHERE dynamic_id=? "
                "AND target=? AND stage=?",
                (dynamic_id, self._target(target), stage),
            ).fetchone()
        return max(0.0, row[0] - self._now()) if row and row[0] else STAGE_SECONDS

    def expire_stage(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state,attempts FROM stages WHERE dynamic_id=? "
                "AND target=? AND stage=?",
                (dynamic_id, self._target(target), stage),
            ).fetchone()
            if (
                not row
                or row[0] in TERMINAL_STATES
                or row[0] in {"uncertain", "blocked"}
            ):
                return
            in_flight = row[0] == "sending"
            result = SendResult(
                delivered=False,
                attempted=in_flight,
                error_code="stage_deadline_inflight"
                if in_flight
                else "stage_deadline_exceeded",
                failure_kind=DeliveryFailureKind.UNCERTAIN
                if in_flight
                else DeliveryFailureKind.PERMANENT,
                attempt_count=row[1],
            )
            db.execute(
                "UPDATE stages SET state=?,result=?,next_retry=0 "
                "WHERE dynamic_id=? AND target=? AND stage=?",
                (
                    "uncertain" if in_flight else "failed",
                    json.dumps(asdict(result)),
                    dynamic_id,
                    self._target(target),
                    stage,
                ),
            )

    def expire_due(self, dynamic_id: str) -> None:
        from ironsbot.core.platform import ConversationRef

        with self._connect() as db:
            rows = db.execute(
                "SELECT target,stage FROM stages WHERE dynamic_id=? "
                "AND deadline_at>0 AND deadline_at<=? "
                "AND state IN ('pending','retry','waiting')",
                (dynamic_id, self._now()),
            ).fetchall()
        for target, stage in rows:
            data = json.loads(target)
            data["platform"] = Platform(data["platform"])
            self.expire_stage(dynamic_id, ConversationRef(**data), stage)

    def block_following(
        self, dynamic_id: str, target: ConversationRef, stage: str
    ) -> None:
        with self._connect() as db:
            self._block_following_db(db, dynamic_id, self._target(target), stage)

    @staticmethod
    def _block_following_db(
        db: sqlite3.Connection, dynamic_id: str, target: str, stage: str
    ) -> None:
        rows = db.execute(
            "SELECT stage FROM stages WHERE dynamic_id=? AND target=? "
            "AND state IN ('pending','retry','waiting')",
            (dynamic_id, target),
        ).fetchall()
        for row in rows:
            if stage not in predecessors(row[0]):
                continue
            result = SendResult(
                delivered=False,
                attempted=False,
                error_code="preceding_stage_uncertain",
                failure_kind=DeliveryFailureKind.UNCERTAIN,
            )
            db.execute(
                "UPDATE stages SET state='blocked',result=?,next_retry=0 "
                "WHERE dynamic_id=? AND target=? AND stage=?",
                (
                    json.dumps(asdict(result)),
                    dynamic_id,
                    target,
                    row[0],
                ),
            )

    def defer_stage(
        self, dynamic_id: str, target: ConversationRef, stage: str, result: SendResult
    ) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE stages SET state='waiting',result=?,"
                "started_at=CASE WHEN attempts=0 THEN 0 ELSE started_at END,"
                "deadline_at=CASE WHEN attempts=0 THEN 0 ELSE deadline_at END "
                "WHERE dynamic_id=? AND target=? AND stage=? "
                "AND state IN ('pending','retry','waiting')",
                (json.dumps(asdict(result)), dynamic_id, self._target(target), stage),
            )
