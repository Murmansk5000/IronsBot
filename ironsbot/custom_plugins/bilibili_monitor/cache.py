import json
import sqlite3
import time

from nonebot.log import logger

from .config import plugin_config
from .state import COOKIE_CACHE_FILE, DYNAMIC_HISTORY_DB_FILE


def _connect() -> sqlite3.Connection:
    DYNAMIC_HISTORY_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DYNAMIC_HISTORY_DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS checkpoints (
            uid INTEGER PRIMARY KEY,
            pub_ts INTEGER NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dynamics (
            dynamic_id TEXT PRIMARY KEY,
            uid INTEGER NOT NULL,
            author_name TEXT NOT NULL,
            pub_ts INTEGER NOT NULL,
            brief TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            pushed INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bili_dynamics_uid_time
        ON dynamics (uid, pub_ts DESC)
        """
    )
    return conn


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
    if not COOKIE_CACHE_FILE.exists():
        return ""

    return COOKIE_CACHE_FILE.read_text(encoding="utf-8").strip()


def save_new_cookie(cookie_str: str) -> None:
    COOKIE_CACHE_FILE.write_text(cookie_str, encoding="utf-8")


def _dynamic_id(item: dict) -> str:
    return str(item.get("id_str") or item.get("id") or "")


def save_dynamic_history_item(  # noqa: PLR0913
    item: dict,
    *,
    pub_ts: int,
    author_mid: int,
    author_name: str,
    brief: str,
    pushed: bool = False,
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
                    raw_json, pushed, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dynamic_id) DO UPDATE SET
                    uid = excluded.uid,
                    author_name = excluded.author_name,
                    pub_ts = excluded.pub_ts,
                    brief = excluded.brief,
                    raw_json = excluded.raw_json,
                    pushed = max(dynamics.pushed, excluded.pushed),
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
                (plugin_config.bili_history_max_items,),
            )
    except (sqlite3.Error, TypeError, ValueError) as e:
        logger.warning(f"failed to save Bilibili dynamic history: {e}")
