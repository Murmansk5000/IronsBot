from __future__ import annotations

import logging
import sqlite3
import time
from typing import TYPE_CHECKING, Literal, cast

from ironsbot.core.messaging import MessageTarget
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration
from ironsbot.services.bilibili.image_delivery_retries import PendingImageDelivery

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


_LOGGER = logging.getLogger(__name__)
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS pending_image_deliveries ("
    "dynamic_id TEXT NOT NULL, target_type TEXT NOT NULL, "
    "target_id INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, "
    "created_at REAL NOT NULL, updated_at REAL NOT NULL, "
    "PRIMARY KEY (dynamic_id, target_type, target_id)"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_pending_image_deliveries_updated "
    "ON pending_image_deliveries (updated_at ASC)",
)


class SqliteBiliImageDeliveryRetryStore:
    """A cache-backed outbox for Bilibili image deliveries only."""

    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=(SqliteMigration(1, _SCHEMA),),
            row_factory=sqlite3.Row,
        )

    def record_failed(
        self,
        dynamic_id: str,
        targets: Iterable[MessageTarget],
    ) -> None:
        now = time.time()
        rows = [
            (dynamic_id, target.target_type, target.target_id, now, now)
            for target in dict.fromkeys(targets)
            if target.target_type in {"group", "private"}
        ]
        if not dynamic_id or not rows:
            return
        try:
            with self._database.connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO pending_image_deliveries (
                        dynamic_id, target_type, target_id, attempts,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, 1, ?, ?)
                    ON CONFLICT(dynamic_id, target_type, target_id) DO UPDATE SET
                        attempts = pending_image_deliveries.attempts + 1,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
        except sqlite3.Error as error:
            _LOGGER.warning("failed to record Bilibili image retry: %s", error)

    def list_pending(self, *, limit: int = 100) -> list[PendingImageDelivery]:
        if limit <= 0:
            return []
        try:
            with self._database.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT dynamic_id, target_type, target_id, attempts
                    FROM pending_image_deliveries
                    ORDER BY
                        updated_at ASC, dynamic_id ASC, target_type ASC, target_id ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.Error as error:
            _LOGGER.warning("failed to read Bilibili image retries: %s", error)
            return []
        return [
            PendingImageDelivery(
                str(row["dynamic_id"]),
                MessageTarget(
                    cast(
                        "Literal['private', 'group']",
                        str(row["target_type"]),
                    ),
                    int(row["target_id"]),
                ),
                int(row["attempts"]),
            )
            for row in rows
        ]

    def resolve(
        self,
        dynamic_id: str,
        targets: Iterable[MessageTarget],
    ) -> None:
        rows = [
            (dynamic_id, target.target_type, target.target_id)
            for target in dict.fromkeys(targets)
            if target.target_type in {"group", "private"}
        ]
        if not dynamic_id or not rows:
            return
        try:
            with self._database.connect() as conn:
                conn.executemany(
                    """
                    DELETE FROM pending_image_deliveries
                    WHERE dynamic_id = ? AND target_type = ? AND target_id = ?
                    """,
                    rows,
                )
        except sqlite3.Error as error:
            _LOGGER.warning("failed to resolve Bilibili image retries: %s", error)
