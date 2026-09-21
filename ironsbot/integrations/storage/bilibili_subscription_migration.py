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
            connection.execute(
                "INSERT OR IGNORE INTO push_unsubscriptions "
                "(principal_kind,principal_id,conversation_platform,"
                "conversation_account_id,conversation_kind,conversation_id,"
                "subscription_key,feature,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    row["principal_kind"],
                    row["principal_id"],
                    row["conversation_platform"],
                    row["conversation_account_id"],
                    row["conversation_kind"],
                    row["conversation_id"],
                    f"bili_media:{uid}:{stage}",
                    row["feature"],
                    row["created_at"],
                ),
            )
        connection.execute(
            "DELETE FROM push_unsubscriptions WHERE principal_kind=? "
            "AND principal_id=? AND subscription_key=?",
            (row["principal_kind"], row["principal_id"], row["subscription_key"]),
        )
    connection.execute("INSERT INTO bili_subscription_migrations VALUES (1)")
