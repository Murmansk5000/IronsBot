from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    ensure_sqlite_columns,
)
from ironsbot.services.bilibili.dynamic_history import DynamicHistoryRecord
from ironsbot.services.bilibili.parser import dynamic_id

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from ironsbot.services.bilibili.push import DynamicHistorySnapshot

_LOGGER = logging.getLogger(__name__)
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS checkpoints ("
    "uid INTEGER PRIMARY KEY, pub_ts INTEGER NOT NULL, updated_at REAL NOT NULL"
    ")",
    "CREATE TABLE IF NOT EXISTS dynamics ("
    "dynamic_id TEXT PRIMARY KEY, uid INTEGER NOT NULL, "
    "author_name TEXT NOT NULL, pub_ts INTEGER NOT NULL, brief TEXT NOT NULL, "
    "raw_json TEXT NOT NULL, pushed INTEGER NOT NULL DEFAULT 0, "
    "suppressed INTEGER NOT NULL DEFAULT 0, "
    "suppression_reason TEXT NOT NULL DEFAULT '', "
    "created_at REAL NOT NULL, updated_at REAL NOT NULL"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_bili_dynamics_uid_time "
    "ON dynamics (uid, pub_ts DESC)",
)

_DELIVERY_CLAIM_COLUMNS = {
    "delivery_claimed_at": "delivery_claimed_at REAL NOT NULL DEFAULT 0",
}
DEFAULT_DELIVERY_CLAIM_SECONDS = 120.0


def _ensure_dynamic_columns(conn: sqlite3.Connection) -> None:
    ensure_sqlite_columns(
        conn,
        table_name="dynamics",
        columns={
            "suppressed": "suppressed INTEGER NOT NULL DEFAULT 0",
            "suppression_reason": "suppression_reason TEXT NOT NULL DEFAULT ''",
        },
    )


def _ensure_delivery_claim_columns(conn: sqlite3.Connection) -> None:
    ensure_sqlite_columns(
        conn,
        table_name="dynamics",
        columns=_DELIVERY_CLAIM_COLUMNS,
    )


_MIGRATIONS = (
    SqliteMigration(1, _SCHEMA, _ensure_dynamic_columns),
    SqliteMigration(2, callback=_ensure_delivery_claim_columns),
)


def _record_from_row(row: sqlite3.Row) -> DynamicHistoryRecord | None:
    try:
        raw_item = json.loads(str(row["raw_json"]))
        if not isinstance(raw_item, dict):
            return None

        return DynamicHistoryRecord(
            str(row["dynamic_id"]),
            int(row["uid"]),
            str(row["author_name"]),
            int(row["pub_ts"]),
            str(row["brief"]),
            raw_item,
            bool(row["pushed"]),
            bool(row["suppressed"]),
            str(row["suppression_reason"] or ""),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
        _LOGGER.warning("failed to parse Bilibili dynamic history row: %s", e)
        return None


class SqliteBiliDynamicHistoryStore:
    def __init__(self, path: str | Path, max_items: int) -> None:
        self.max_items = max_items
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            row_factory=sqlite3.Row,
        )

    def get_checkpoints(self) -> dict[int, int]:
        try:
            with self._database.connect() as conn:
                rows = conn.execute(
                    "SELECT uid, pub_ts FROM checkpoints WHERE pub_ts > 0"
                ).fetchall()
                return {int(uid): int(pub_ts) for uid, pub_ts in rows}
        except sqlite3.Error as e:
            _LOGGER.warning("failed to read Bilibili checkpoints: %s", e)
            return {}

    def save_checkpoints(self, checkpoints: dict[int, int]) -> None:
        cleaned = {
            int(uid): int(pub_time)
            for uid, pub_time in sorted(checkpoints.items())
            if int(pub_time) > 0
        }
        try:
            with self._database.connect() as conn:
                conn.executemany(
                    """
                    REPLACE INTO checkpoints (uid, pub_ts, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (uid, pub_time, time.time())
                        for uid, pub_time in cleaned.items()
                    ],
                )
        except sqlite3.Error as e:
            _LOGGER.warning("failed to write Bilibili checkpoints: %s", e)

    def save_item(  # noqa: PLR0913
        self,
        item: dict,
        *,
        pub_ts: int,
        author_mid: int,
        author_name: str,
        brief: str,
        pushed: bool = False,
        suppressed: bool = False,
        suppression_reason: str = "",
    ) -> None:
        item_id = dynamic_id(item) or f"{author_mid}:{pub_ts}"
        now = time.time()
        try:
            raw_json = json.dumps(item, ensure_ascii=False)
            with self._database.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO dynamics (
                        dynamic_id, uid, author_name, pub_ts, brief,
                        raw_json, pushed, suppressed, suppression_reason,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(dynamic_id) DO UPDATE SET
                        uid = excluded.uid,
                        author_name = excluded.author_name,
                        pub_ts = excluded.pub_ts,
                        brief = excluded.brief,
                        raw_json = excluded.raw_json,
                        pushed = max(dynamics.pushed, excluded.pushed),
                        suppressed = max(dynamics.suppressed, excluded.suppressed),
                        suppression_reason = CASE
                            WHEN excluded.suppression_reason != ''
                            THEN excluded.suppression_reason
                            ELSE dynamics.suppression_reason
                        END,
                        delivery_claimed_at = CASE
                            WHEN excluded.pushed = 1 THEN 0
                            ELSE dynamics.delivery_claimed_at
                        END,
                        updated_at = excluded.updated_at
                    """,
                    (
                        item_id,
                        int(author_mid),
                        author_name,
                        int(pub_ts),
                        brief,
                        raw_json,
                        1 if pushed else 0,
                        1 if suppressed else 0,
                        suppression_reason,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """
                    DELETE FROM dynamics
                    WHERE dynamic_id IN (
                        SELECT dynamic_id
                        FROM dynamics
                        ORDER BY pub_ts DESC, updated_at DESC
                        LIMIT -1 OFFSET ?
                    )
                    """,
                    (self.max_items,),
                )
        except (sqlite3.Error, TypeError, ValueError) as e:
            _LOGGER.warning("failed to save Bilibili dynamic history: %s", e)

    def save_snapshot(self, snapshot: DynamicHistorySnapshot) -> None:
        self.save_item(
            snapshot.item,
            pub_ts=snapshot.pub_ts,
            author_mid=snapshot.author_mid,
            author_name=snapshot.author_name,
            brief=snapshot.brief,
            pushed=snapshot.pushed,
            suppressed=snapshot.suppressed,
            suppression_reason=snapshot.suppression_reason,
        )

    def list(
        self,
        *,
        limit: int = 10,
        uid: int | None = None,
        uids: Iterable[int] | None = None,
    ) -> list[DynamicHistoryRecord]:
        query = (
            "SELECT dynamic_id, uid, author_name, pub_ts, brief, raw_json, "
            "pushed, suppressed, suppression_reason FROM dynamics"
        )
        params: list[int] = []
        uid_list = (
            list(dict.fromkeys(int(value) for value in uids if int(value) > 0))
            if uids is not None
            else []
        )
        if uids is not None and not uid_list:
            return []
        if uid_list:
            query += f" WHERE uid IN ({','.join('?' for _ in uid_list)})"
            params.extend(uid_list)
        elif uid is not None:
            query += " WHERE uid = ?"
            params.append(int(uid))
        query += " ORDER BY pub_ts DESC, updated_at DESC LIMIT ?"
        params.append(int(limit))

        try:
            with self._database.connect() as conn:
                rows = conn.execute(query, params).fetchall()
        except sqlite3.Error as e:
            _LOGGER.warning("failed to list Bilibili dynamic history: %s", e)
            return []
        return [
            record
            for row in rows
            if (record := _record_from_row(row)) is not None
        ]

    def get(self, dynamic_id: str) -> DynamicHistoryRecord | None:
        try:
            with self._database.connect() as conn:
                row = conn.execute(
                    """
                    SELECT dynamic_id, uid, author_name, pub_ts, brief, raw_json,
                        pushed, suppressed, suppression_reason
                    FROM dynamics
                    WHERE dynamic_id = ?
                    """,
                    (dynamic_id,),
                ).fetchone()
        except sqlite3.Error as e:
            _LOGGER.warning("failed to read Bilibili dynamic history item: %s", e)
            return None
        return _record_from_row(row) if row is not None else None

    def try_claim_delivery(
        self,
        dynamic_id: str,
        *,
        claim_seconds: float = DEFAULT_DELIVERY_CLAIM_SECONDS,
    ) -> bool:
        """Atomically reserve an unpushed dynamic for one delivery attempt."""

        now = time.time()
        expired_before = now - max(float(claim_seconds), 0.0)
        try:
            with self._database.connect() as conn:
                result = conn.execute(
                    """
                    UPDATE dynamics
                    SET delivery_claimed_at = ?
                    WHERE dynamic_id = ?
                      AND pushed = 0
                      AND delivery_claimed_at <= ?
                    """,
                    (now, dynamic_id, expired_before),
                )
                return result.rowcount == 1
        except sqlite3.Error as e:
            _LOGGER.warning("failed to claim Bilibili dynamic delivery: %s", e)
            return False

    def release_delivery_claim(self, dynamic_id: str) -> None:
        try:
            with self._database.connect() as conn:
                conn.execute(
                    """
                    UPDATE dynamics
                    SET delivery_claimed_at = 0
                    WHERE dynamic_id = ? AND pushed = 0
                    """,
                    (dynamic_id,),
                )
        except sqlite3.Error as e:
            _LOGGER.warning("failed to release Bilibili dynamic delivery claim: %s", e)
