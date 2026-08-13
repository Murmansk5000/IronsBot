# SPDX-License-Identifier: MIT
"""One-time conversion of account-wide opt-outs into independent stages."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Set as AbstractSet


def migrate_bilibili_subscriptions(
    connection: sqlite3.Connection, classified_uids: AbstractSet[int]
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS bili_subscription_migrations "
        "(version INTEGER PRIMARY KEY)"
    )
    if connection.execute(
        "SELECT 1 FROM bili_subscription_migrations WHERE version=1"
    ).fetchone():
        return
    connection.execute(
        "CREATE TABLE IF NOT EXISTS bili_subscription_legacy AS "
        "SELECT * FROM push_unsubscriptions WHERE subscription_key LIKE 'bili_%'"
    )
    # Ordinary accounts previously ignored media opt-outs. Do not activate them.
    for (key,) in connection.execute(
        "SELECT DISTINCT subscription_key FROM push_unsubscriptions "
        "WHERE subscription_key LIKE 'bili_media:%'"
    ).fetchall():
        _prefix, _, suffix = key.partition(":")
        uid, _, _stage = suffix.partition(":")
        if uid.isdigit() and int(uid) not in classified_uids:
            connection.execute(
                "DELETE FROM push_unsubscriptions WHERE subscription_key=?", (key,)
            )
    cursor = connection.execute(
        "SELECT * FROM push_unsubscriptions WHERE subscription_key LIKE 'bili_push:%'"
    )
    names = [column[0] for column in cursor.description]
    for values in cursor.fetchall():
        row = dict(zip(names, values, strict=True))
        uid = row["subscription_key"].removeprefix("bili_push:")
        if not uid.isdigit():
            continue
        for stage in ("link", "text", "image"):
            copied = {**row, "subscription_key": f"bili_media:{uid}:{stage}"}
            columns = tuple(copied)
            connection.execute(
                "INSERT OR IGNORE INTO push_unsubscriptions (" + ",".join(columns)
                + ") VALUES (" + ",".join("?" for _ in columns) + ")",
                tuple(copied.values()),
            )
        owner = [name for name in row if name not in {"feature", "created_at"}]
        connection.execute(
            "DELETE FROM push_unsubscriptions WHERE " + " AND ".join(name + "=?" for name in owner),
            tuple(row[name] for name in owner),
        )
    connection.execute("INSERT INTO bili_subscription_migrations VALUES (1)")
