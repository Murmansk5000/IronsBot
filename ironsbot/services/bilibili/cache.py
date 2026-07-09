import json
import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nonebot.log import logger

from ironsbot.config.loader import get_app_config
from ironsbot.services.bilibili.push import (
    DynamicHistorySnapshot,
    build_dynamic_history_snapshot_for_item,
)
from ironsbot.services.bilibili.state import cookie_cache_file, dynamic_history_db_file
from ironsbot.shared.sqlite import ensure_sqlite_column, open_sqlite_schema


@dataclass(frozen=True, slots=True)
class DynamicHistoryRecord:
    dynamic_id: str
    uid: int
    author_name: str
    pub_ts: int
    brief: str
    item: dict[str, Any]
    pushed: bool
    suppressed: bool
    suppression_reason: str


BILI_DYNAMIC_HISTORY_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS checkpoints (
        uid INTEGER PRIMARY KEY,
        pub_ts INTEGER NOT NULL,
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dynamics (
        dynamic_id TEXT PRIMARY KEY,
        uid INTEGER NOT NULL,
        author_name TEXT NOT NULL,
        pub_ts INTEGER NOT NULL,
        brief TEXT NOT NULL,
        raw_json TEXT NOT NULL,
        pushed INTEGER NOT NULL DEFAULT 0,
        suppressed INTEGER NOT NULL DEFAULT 0,
        suppression_reason TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_bili_dynamics_uid_time
    ON dynamics (uid, pub_ts DESC)
    """,
)


def _connect() -> AbstractContextManager[sqlite3.Connection]:
    db_file = dynamic_history_db_file()
    return _connect_dynamic_history(db_file)


@contextmanager
def _connect_dynamic_history(
    db_file: str | Path,
) -> Iterator[sqlite3.Connection]:
    with open_sqlite_schema(
        db_file,
        BILI_DYNAMIC_HISTORY_SCHEMA,
        row_factory=sqlite3.Row,
    ) as conn:
        _ensure_dynamic_columns(conn)
        yield conn


def _ensure_dynamic_columns(conn: sqlite3.Connection) -> None:
    ensure_sqlite_column(
        conn,
        table_name="dynamics",
        column_name="suppressed",
        column_definition="suppressed INTEGER NOT NULL DEFAULT 0",
    )
    ensure_sqlite_column(
        conn,
        table_name="dynamics",
        column_name="suppression_reason",
        column_definition="suppression_reason TEXT NOT NULL DEFAULT ''",
    )


def get_last_saved_times() -> dict[int, int]:
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT uid, pub_ts FROM checkpoints WHERE pub_ts > 0"
            ).fetchall()
            checkpoints = {int(uid): int(pub_ts) for uid, pub_ts in rows}
            if checkpoints:
                return checkpoints
    except sqlite3.Error as e:
        logger.warning(f"failed to read Bilibili checkpoints from SQLite: {e}")

    return {}


def save_last_saved_times(checkpoints: dict[int, int]) -> None:
    cleaned = {
        int(uid): int(pub_time)
        for uid, pub_time in sorted(checkpoints.items())
        if int(pub_time) > 0
    }
    try:
        with _connect() as conn:
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
        logger.warning(f"failed to write Bilibili checkpoints to SQLite: {e}")


def get_saved_cookie() -> str:
    cache_file = cookie_cache_file()
    if not cache_file.exists():
        return ""

    return cache_file.read_text(encoding="utf-8").strip()


def save_new_cookie(cookie_str: str) -> None:
    cache_file = cookie_cache_file()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(cookie_str, encoding="utf-8")


def _dynamic_id(item: dict) -> str:
    return str(item.get("id_str") or item.get("id") or "")


def dynamic_id_for_item(item: dict) -> str:
    return _dynamic_id(item)


def save_dynamic_history_item(  # noqa: PLR0913
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
    dynamic_id = _dynamic_id(item) or f"{author_mid}:{pub_ts}"
    now = time.time()
    try:
        raw_json = json.dumps(item, ensure_ascii=False)
        with _connect() as conn:
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
                    updated_at = excluded.updated_at
                """,
                (
                    dynamic_id,
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
                (get_app_config().bilibili.storage.history_max_items,),
            )
    except (sqlite3.Error, TypeError, ValueError) as e:
        logger.warning(f"failed to save Bilibili dynamic history: {e}")


def save_dynamic_history_snapshot(snapshot: DynamicHistorySnapshot) -> None:
    save_dynamic_history_item(
        snapshot.item,
        pub_ts=snapshot.pub_ts,
        author_mid=snapshot.author_mid,
        author_name=snapshot.author_name,
        brief=snapshot.brief,
        pushed=snapshot.pushed,
        suppressed=snapshot.suppressed,
        suppression_reason=snapshot.suppression_reason,
    )


def save_target_dynamic_history(
    target_dynamics: Iterable[tuple[int, dict[str, Any]]],
    *,
    suppress_patterns: list[str],
) -> int:
    saved_count = 0
    for pub_ts, item in target_dynamics:
        snapshot = build_dynamic_history_snapshot_for_item(
            item,
            pub_ts=pub_ts,
            suppress_patterns=suppress_patterns,
        )
        if snapshot is None:
            continue

        save_dynamic_history_snapshot(snapshot)
        saved_count += 1

    return saved_count


def _record_from_row(row: sqlite3.Row) -> DynamicHistoryRecord | None:
    try:
        raw_item = json.loads(str(row["raw_json"]))
        if not isinstance(raw_item, dict):
            return None

        return DynamicHistoryRecord(
            dynamic_id=str(row["dynamic_id"]),
            uid=int(row["uid"]),
            author_name=str(row["author_name"]),
            pub_ts=int(row["pub_ts"]),
            brief=str(row["brief"]),
            item=raw_item,
            pushed=bool(row["pushed"]),
            suppressed=bool(row["suppressed"]),
            suppression_reason=str(row["suppression_reason"] or ""),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
        logger.warning(f"failed to parse Bilibili dynamic history row: {e}")
        return None


def list_dynamic_history(
    *,
    limit: int = 10,
    uid: int | None = None,
    uids: Iterable[int] | None = None,
) -> list[DynamicHistoryRecord]:
    query = (
        "SELECT dynamic_id, uid, author_name, pub_ts, brief, raw_json, "
        "pushed, suppressed, suppression_reason "
        "FROM dynamics"
    )
    params: list[int] = []
    uid_list = []
    if uids is not None:
        uid_list = list(
            dict.fromkeys(int(raw_uid) for raw_uid in uids if int(raw_uid) > 0)
        )
        if not uid_list:
            return []

    if uid_list:
        placeholders = ",".join("?" for _ in uid_list)
        query += f" WHERE uid IN ({placeholders})"
        params.extend(uid_list)
    elif uid is not None:
        query += " WHERE uid = ?"
        params.append(int(uid))
    query += " ORDER BY pub_ts DESC, updated_at DESC LIMIT ?"
    params.append(int(limit))

    try:
        with _connect() as conn:
            rows = conn.execute(query, params).fetchall()
    except sqlite3.Error as e:
        logger.warning(f"failed to list Bilibili dynamic history: {e}")
        return []

    records: list[DynamicHistoryRecord] = []
    for row in rows:
        record = _record_from_row(row)
        if record is not None:
            records.append(record)
    return records


def get_dynamic_history_item(dynamic_id: str) -> DynamicHistoryRecord | None:
    try:
        with _connect() as conn:
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
        logger.warning(f"failed to read Bilibili dynamic history item: {e}")
        return None

    if row is None:
        return None
    return _record_from_row(row)
