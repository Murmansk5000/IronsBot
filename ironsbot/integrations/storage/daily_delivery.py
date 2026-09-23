# SPDX-License-Identifier: MIT
"""Persistent per-user daily claims, including crash-ambiguous attempts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.messaging.daily_delivery import DailyDeliveryOutcome


class SqliteDailyDeliveryStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migration_namespace="daily_delivery",
            migrations=(
                SqliteMigration(
                    1,
                    (
                        """
                CREATE TABLE IF NOT EXISTS daily_delivery_claims (
                    principal TEXT NOT NULL,
                    day TEXT NOT NULL,
                    status TEXT NOT NULL,
                    PRIMARY KEY (principal, day)
                )
            """,
                    ),
                ),
            ),
        )
        # Establish WAL and the schema before concurrent first claims arrive.
        with self._database.connect():
            pass

    def claim(self, principal: str, day: str) -> bool:
        with self._database.connect() as connection:
            # Claimed rows surviving a crash are ambiguous and never reacquired.
            cursor = connection.execute(
                """
                INSERT INTO daily_delivery_claims VALUES (?, ?, 'claimed')
                ON CONFLICT(principal, day) DO UPDATE SET status='claimed'
                WHERE daily_delivery_claims.status='failed'
            """,
                (principal, day),
            )
            return cursor.rowcount == 1

    def finish(self, principal: str, day: str, outcome: DailyDeliveryOutcome) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE daily_delivery_claims SET status=?
                WHERE principal=? AND day=? AND status='claimed'
            """,
                (outcome, principal, day),
            )
