# SPDX-License-Identifier: MIT
"""Transactional per-message claims and receipts for proactive delivery."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from typing import TYPE_CHECKING

from ironsbot.core.outbound import (
    DeliveryFailureKind,
    ExecutionIdentity,
    OutboundMessage,
    SendResult,
)
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.storage.frozen_message import freeze_message, thaw_message
from ironsbot.integrations.storage.sqlite import SqliteDatabase
from ironsbot.services.messaging.delivery_tasks import DeliveryIntent, StoredDelivery

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)
SHA256_HEX_LENGTH = 64


def decode_result(payload: str) -> SendResult:
    values = json.loads(payload)
    if values.get("failure_kind"):
        values["failure_kind"] = DeliveryFailureKind(values["failure_kind"])
    if identity := values.get("execution_identity"):
        identity["platform"] = Platform(identity["platform"])
        values["execution_identity"] = ExecutionIdentity(**identity)
    values["reply_anchor_ids"] = tuple(values.get("reply_anchor_ids", ()))
    return SendResult(**values)


class SqliteProactiveTasks:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = SqliteDatabase(path)
        self.media_root = path.parent / "proactive_media"
        self._wake: Callable[[], None] | None = None
        self._recovered = False
        with self.db.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS proactive_tasks (
                    id TEXT PRIMARY KEY, target TEXT NOT NULL, message TEXT NOT NULL,
                    intent TEXT NOT NULL, action TEXT NOT NULL, subscription TEXT,
                    max_attempts INTEGER NOT NULL, delays TEXT NOT NULL,
                    expires REAL NOT NULL, sequence_key TEXT NOT NULL,
                    position INTEGER NOT NULL, supersedes TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER DEFAULT 0,
                    next_at REAL DEFAULT 0, result TEXT, reported TEXT DEFAULT '',
                    created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS proactive_due
                    ON proactive_tasks(state,next_at,expires);
                CREATE INDEX IF NOT EXISTS proactive_expiry
                    ON proactive_tasks(expires);
                CREATE TABLE IF NOT EXISTS proactive_accounts (
                    account TEXT PRIMARY KEY, failures INTEGER NOT NULL,
                    next_at REAL NOT NULL);
            """)

    def prepare(self, task: StoredDelivery) -> OutboundMessage:
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT message FROM proactive_tasks WHERE id=?",
                (task.id,),
            ).fetchone()
            if existing is not None:
                return thaw_message(existing[0], self.media_root)
            payload = freeze_message(task.message, self.media_root)
            if task.intent.supersedes:
                db.execute(
                    "UPDATE proactive_tasks SET state='superseded' WHERE supersedes=? "
                    "AND target=? AND id!=? AND state IN ('pending','retry','waiting')",
                    (
                        task.intent.supersedes,
                        json.dumps(asdict(task.conversation)),
                        task.id,
                    ),
                )
            inserted = db.execute(
                "INSERT OR IGNORE INTO proactive_tasks "
                "(id,target,message,intent,action,subscription,max_attempts,delays,"
                "expires,sequence_key,position,supersedes,created) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task.id,
                    json.dumps(asdict(task.conversation)),
                    payload,
                    json.dumps(asdict(task.intent)),
                    task.action,
                    task.subscription,
                    task.max_attempts,
                    json.dumps(task.delays),
                    task.intent.expires_at,
                    task.intent.sequence,
                    task.intent.position,
                    task.intent.supersedes,
                    time.time(),
                ),
            )
            original = db.execute(
                "SELECT message FROM proactive_tasks WHERE id=?",
                (task.id,),
            ).fetchone()
        return (
            task.message
            if inserted.rowcount
            else thaw_message(original[0], self.media_root)
        )

    def recover(self) -> None:
        if self._recovered:
            return
        with self.db.connect() as db:
            db.execute(
                "UPDATE proactive_tasks SET state='uncertain' WHERE state='sending'"
            )
        self._recovered = True

    def set_waker(self, wake: Callable[[], None] | None) -> None:
        self._wake = wake

    def wake(self, account: str = "", *, platform: Platform | None = None) -> None:
        selected_platform = platform.value if platform is not None else ""
        with self.db.connect() as db:
            db.execute(
                "DELETE FROM proactive_accounts WHERE "
                "(?='' OR substr(account,1,instr(account,':')-1)=?) AND "
                "(?='' OR substr(account,instr(account,':')+1)=?)",
                (selected_platform, selected_platform, account, account),
            )
            db.execute(
                "UPDATE proactive_tasks SET next_at=0 WHERE state='waiting' "
                "AND (?='' OR json_extract(target,'$.platform')=?) "
                "AND (?='' OR json_extract(target,'$.account_id')=? "
                "OR json_extract(target,'$.account_id') IS NULL)",
                (selected_platform, selected_platform, account, account),
            )
        if self._wake is not None:
            self._wake()

    @staticmethod
    def _account(target: ConversationRef) -> str:
        return f"{target.platform.value}:{target.account_id or ''}"

    def account_ready(self, target: ConversationRef) -> bool:
        with self.db.connect() as db:
            row = db.execute(
                "SELECT next_at FROM proactive_accounts WHERE account=?",
                (self._account(target),),
            ).fetchone()
        return row is None or row[0] <= time.time()

    def account_failed(self, target: ConversationRef) -> None:
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT failures FROM proactive_accounts WHERE account=?",
                (self._account(target),),
            ).fetchone()
            failures = min(5, row[0] + 1 if row else 1)
            db.execute(
                "INSERT OR REPLACE INTO proactive_accounts VALUES (?,?,?)",
                (
                    self._account(target),
                    failures,
                    time.time() + min(300, 30 * 2 ** (failures - 1)),
                ),
            )

    def claim(self, task_id: str) -> bool:
        with self.db.connect() as db:
            return (
                db.execute(
                    "UPDATE proactive_tasks SET state='sending' WHERE id=? "
                    "AND state IN ('pending','retry','waiting') AND next_at<=? "
                    "AND expires>? AND attempts<max_attempts AND NOT EXISTS "
                    "(SELECT 1 FROM proactive_tasks previous WHERE "
                    "previous.sequence_key=proactive_tasks.sequence_key "
                    "AND previous.target=proactive_tasks.target AND previous.position "
                    "<proactive_tasks.position AND proactive_tasks.sequence_key!='' "
                    "AND previous.state!='success')",
                    (task_id, time.time(), time.time()),
                ).rowcount
                == 1
            )

    def finish(self, task_id: str, result: SendResult) -> None:
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT attempts,max_attempts,delays FROM proactive_tasks "
                "WHERE id=? AND state='sending'",
                (task_id,),
            ).fetchone()
            if row is None:
                return
            waiting = result.failure_kind is DeliveryFailureKind.TRANSPORT_UNAVAILABLE
            attempts = row[0] + (not waiting)
            state = "success" if result.delivered else "permanent"
            delay = 0.0
            if waiting:
                state, delay = "waiting", 30.0
            elif result.failure_kind is DeliveryFailureKind.UNCERTAIN:
                state = "uncertain"
            elif (
                result.failure_kind is DeliveryFailureKind.RETRYABLE
                and attempts < row[1]
            ):
                state = "retry"
                delays = json.loads(row[2])
                delay = (
                    delays[min(max(0, attempts - 1), len(delays) - 1)]
                    if delays
                    else 2.0
                )
            db.execute(
                "UPDATE proactive_tasks SET state=?,attempts=?,next_at=?,result=? "
                "WHERE id=? AND state='sending'",
                (
                    state,
                    attempts,
                    time.time() + delay,
                    json.dumps(asdict(result)),
                    task_id,
                ),
            )

    def result(self, task_id: str) -> SendResult:
        with self.db.connect() as db:
            row = db.execute(
                "SELECT result FROM proactive_tasks WHERE id=?", (task_id,)
            ).fetchone()
        return (
            decode_result(row[0])
            if row and row[0]
            else SendResult(
                delivered=False,
                error_code="delivery_pending",
                attempted=False,
                failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
            )
        )

    def due(self) -> list[StoredDelivery]:
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE proactive_tasks SET state='blocked' "
                "WHERE state IN ('pending','retry','waiting') AND sequence_key!='' "
                "AND EXISTS (SELECT 1 FROM proactive_tasks previous "
                "WHERE previous.sequence_key=proactive_tasks.sequence_key "
                "AND previous.target=proactive_tasks.target "
                "AND previous.position<proactive_tasks.position "
                "AND previous.state IN "
                "('permanent','uncertain','expired','superseded'))"
            )
            db.execute(
                "UPDATE proactive_tasks SET state='expired' WHERE expires<=? "
                "AND state IN ('pending','retry','waiting','blocked')",
                (time.time(),),
            )
            rows = db.execute(
                "SELECT id,target,message,intent,action,subscription,"
                "max_attempts,delays "
                "FROM proactive_tasks WHERE state IN ('pending','retry','waiting') "
                "AND next_at<=? AND expires>? ORDER BY created,position",
                (time.time(), time.time()),
            ).fetchall()
            self._prune_media(db)
        tasks = []
        for row in rows:
            try:
                target = json.loads(row[1])
                target["platform"] = Platform(target["platform"])
                tasks.append(
                    StoredDelivery(
                        row[0],
                        ConversationRef(**target),
                        thaw_message(row[2], self.media_root),
                        DeliveryIntent(**json.loads(row[3])),
                        row[4],
                        row[5],
                        row[6],
                        tuple(json.loads(row[7])),
                    )
                )
            except (ValueError, OSError, KeyError):  # noqa: PERF203 - isolate corrupt assets
                self.skip(row[0], "frozen_media_unavailable")
        return tasks

    def _prune_media(self, db: sqlite3.Connection) -> None:
        if not self.media_root.exists():
            return
        required: set[str] = set()
        try:
            for row in db.execute(
                "SELECT message FROM proactive_tasks WHERE expires>?", (time.time(),)
            ):
                for entry in json.loads(row[0]):
                    for media in json.loads(entry.get("media", "[]")):
                        if "sha256" in media:
                            required.add(media["sha256"])
            for path in self.media_root.iterdir():
                if (
                    len(path.name) == SHA256_HEX_LENGTH
                    and all(char in "0123456789abcdef" for char in path.name)
                    and path.name not in required
                ):
                    path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            logger.warning("proactive media cleanup deferred")

    def skip(self, task_id: str, reason: str) -> None:
        with self.db.connect() as db:
            db.execute(
                "UPDATE proactive_tasks SET state='permanent',result=? WHERE id=? "
                "AND state IN ('pending','waiting','retry')",
                (
                    json.dumps(
                        asdict(
                            SendResult(
                                delivered=False,
                                error_code=reason,
                                attempted=False,
                                failure_kind=DeliveryFailureKind.PERMANENT,
                            )
                        )
                    ),
                    task_id,
                ),
            )

    def changes(self) -> dict[str, int]:
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT state,COUNT(*) FROM proactive_tasks "
                "WHERE state!=reported AND action!='proactive recovery summary' "
                "AND (state!='success' OR reported IN ('retry','waiting','uncertain')) "
                "GROUP BY state"
            ).fetchall()
            db.execute(
                "UPDATE proactive_tasks SET reported=state WHERE state!=reported"
            )
        return dict(rows)
