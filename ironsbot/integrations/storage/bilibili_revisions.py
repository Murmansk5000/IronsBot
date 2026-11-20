# SPDX-License-Identifier: MIT
"""Transactional revision snapshots and outbox, sharing the delivery database."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.integrations.storage.sqlite import open_sqlite_connection
from ironsbot.services.bilibili.parser import dynamic_content
from ironsbot.services.bilibili.revisions import (
    REVISION_META,
    REVISION_RETENTION,
    clean_revision,
    complete_revision,
    media_changed,
    visible_signature,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class SqliteBiliRevisionStore:
    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open_sqlite_connection(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS dynamic_revision_heads (
                    id TEXT PRIMARY KEY, uid INTEGER NOT NULL, pub_ts REAL NOT NULL,
                    sequence INTEGER NOT NULL, signature TEXT NOT NULL,
                    item TEXT NOT NULL, delivery_key TEXT NOT NULL,
                    checked REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS dynamic_revision_events (
                    key TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                    pub_ts REAL NOT NULL, item TEXT NOT NULL,
                    registered INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS dynamic_revision_seeds (
                    id TEXT PRIMARY KEY);
            """)

    def observe(
        self,
        item: dict[str, Any],
        pub_ts: int,
        uid: int,
        *,
        clock: float | None = None,
        baseline_only: bool = False,
    ) -> str | None:
        now = time.time() if clock is None else clock
        if (
            not 0 <= now - pub_ts < REVISION_RETENTION
            or not complete_revision(item)
            or not (source_id := str(item.get("id_str", "")))
        ):
            return None
        item = clean_revision(item)
        signature = visible_signature(item)
        with open_sqlite_connection(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT sequence,signature,item,delivery_key,uid,pub_ts "
                "FROM dynamic_revision_heads WHERE id=?",
                (source_id,),
            ).fetchone()
            if previous is not None and baseline_only:
                return None
            if previous is not None and (previous[4] != uid or previous[5] != pub_ts):
                return None
            seeded = (
                db.execute(
                    "DELETE FROM dynamic_revision_seeds WHERE id=?", (source_id,)
                ).rowcount
                > 0
            )
            if baseline_only:
                db.execute(
                    "INSERT INTO dynamic_revision_seeds VALUES (?)", (source_id,)
                )
            if previous is not None and previous[1] == signature:
                db.execute(
                    "UPDATE dynamic_revision_heads SET checked=? WHERE id=?",
                    (now, source_id),
                )
                return None
            changed = previous is not None and not seeded
            sequence = previous[0] + 1 if changed else 0
            key = f"{source_id}:edit:{sequence}" if changed else source_id
            if changed:
                before = json.loads(previous[2])
                edited = {
                    **item,
                    REVISION_META: {
                        "key": key,
                        "previous_key": previous[3],
                        "before": before,
                        "text_changed": dynamic_content(before).replace("\r\n", "\n")
                        != dynamic_content(item).replace("\r\n", "\n"),
                        "images_changed": media_changed(before, item),
                        "observed_at": now,
                        "sequence": sequence,
                        "published_at": pub_ts,
                    },
                }
                db.execute(
                    "INSERT INTO dynamic_revision_events VALUES (?,?,?,?,0)",
                    (key, source_id, pub_ts, json.dumps(edited)),
                )
            db.execute(
                "INSERT OR REPLACE INTO dynamic_revision_heads "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    source_id,
                    uid,
                    pub_ts,
                    sequence,
                    signature,
                    json.dumps(item),
                    key,
                    now,
                ),
            )
            return key if changed else None

    def pending(self, *, clock: float | None = None) -> list[dict[str, Any]]:
        now = time.time() if clock is None else clock
        with open_sqlite_connection(self.path) as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT item FROM dynamic_revision_events "
                    "WHERE registered=0 AND pub_ts>? ORDER BY rowid",
                    (now - REVISION_RETENTION,),
                )
            ]

    def acknowledge(self, key: str) -> None:
        with open_sqlite_connection(self.path) as db:
            db.execute(
                "UPDATE dynamic_revision_events SET registered=1 WHERE key=?", (key,)
            )

    def due(
        self, excluded: set[str], *, clock: float | None = None
    ) -> list[tuple[str, int]]:
        now = time.time() if clock is None else clock
        with open_sqlite_connection(self.path) as db:
            rows = db.execute(
                "SELECT id,uid FROM dynamic_revision_heads WHERE pub_ts>? "
                "ORDER BY checked,id",
                (now - REVISION_RETENTION,),
            )
            selected = [(row[0], row[1]) for row in rows if row[0] not in excluded][:10]
            db.executemany(
                "UPDATE dynamic_revision_heads SET checked=? WHERE id=?",
                [(now, source_id) for source_id, _uid in selected],
            )
            return selected

    def prune(self, *, clock: float | None = None) -> None:
        now = time.time() if clock is None else clock
        with open_sqlite_connection(self.path) as db:
            for table in ("dynamic_revision_heads", "dynamic_revision_events"):
                db.execute(
                    f"DELETE FROM {table} WHERE pub_ts<=?", (now - REVISION_RETENTION,)
                )
            db.execute(
                "DELETE FROM dynamic_revision_seeds "
                "WHERE id NOT IN (SELECT id FROM dynamic_revision_heads)"
            )
