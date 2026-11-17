# SPDX-License-Identifier: MIT
"""Durable live observations and notices; delivery receipts remain in the outbox."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration
from ironsbot.services.bilibili.live_models import (
    LiveAccount,
    LiveNotice,
    LiveSchedule,
)

if TYPE_CHECKING:
    from pathlib import Path

_SCHEMA = (
    "CREATE TABLE live_accounts (uid INTEGER PRIMARY KEY, state TEXT NOT NULL)",
    "CREATE TABLE live_notices (key TEXT PRIMARY KEY, expires REAL NOT NULL, "
    "available REAL NOT NULL, "
    "completed INTEGER NOT NULL DEFAULT 0, notice TEXT NOT NULL)",
)


def _notice(raw: str) -> LiveNotice:
    data = json.loads(raw)
    data["targets"] = tuple(
        ConversationRef(
            Platform(row["platform"]),
            row["kind"],
            row["id"],
            account_id=row["account_id"],
        )
        for row in data["targets"]
    )
    return LiveNotice(**data)


class SqliteBiliLiveStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(path, (SqliteMigration(1, _SCHEMA),))

    def account(self, uid: int) -> LiveAccount:
        with self._database.connect() as conn:
            row = conn.execute(
                "SELECT state FROM live_accounts WHERE uid=?", (uid,)
            ).fetchone()
        if row is None:
            return LiveAccount(uid)
        data = json.loads(row[0])
        data["schedules"] = [LiveSchedule(**entry) for entry in data["schedules"]]
        return LiveAccount(**data)

    def save(self, account: LiveAccount, notices: tuple[LiveNotice, ...] = ()) -> None:
        with self._database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO live_accounts VALUES (?,?) ON CONFLICT(uid) "
                "DO UPDATE SET state=excluded.state",
                (account.uid, json.dumps(asdict(account), ensure_ascii=False)),
            )
            for notice in notices:
                conn.execute(
                    "INSERT OR IGNORE INTO live_notices(key,expires,available,notice) "
                    "VALUES (?,?,?,?)",
                    (
                        notice.key,
                        notice.expires_at,
                        notice.created_at,
                        json.dumps(asdict(notice), ensure_ascii=False),
                    ),
                )

    def add_notice(self, notice: LiveNotice) -> None:
        with self._database.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO live_notices(key,expires,available,notice) "
                "VALUES (?,?,?,?)",
                (
                    notice.key,
                    notice.expires_at,
                    notice.created_at,
                    json.dumps(asdict(notice), ensure_ascii=False),
                ),
            )

    def notices(self, now: float) -> list[LiveNotice]:
        with self._database.connect() as conn:
            rows = conn.execute(
                "SELECT notice FROM live_notices WHERE completed=0 "
                "AND expires>? AND available<=? ORDER BY rowid",
                (now, now),
            ).fetchall()
        return [_notice(row[0]) for row in rows]

    def notice(self, key: str) -> LiveNotice | None:
        with self._database.connect() as conn:
            row = conn.execute(
                "SELECT notice FROM live_notices WHERE key=?", (key,)
            ).fetchone()
        return _notice(row[0]) if row else None

    def complete(self, key: str) -> None:
        with self._database.connect() as conn:
            conn.execute("UPDATE live_notices SET completed=1 WHERE key=?", (key,))

    def prune(self, now: float) -> None:
        # Recent identities are diagnostic only; outbox receipts are never deleted here.
        with self._database.connect() as conn:
            conn.execute(
                "DELETE FROM live_notices WHERE expires<?", (now - 30 * 86400,)
            )
