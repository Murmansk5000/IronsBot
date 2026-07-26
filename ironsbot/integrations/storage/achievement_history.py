# SPDX-License-Identifier: MIT
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ironsbot.core.time import TZ_CN
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration
from ironsbot.services.seer.achievement_history import (
    AchievementComparison,
    AchievementRecord,
    AchievementSnapshot,
    AchievementSnapshotVersion,
)

if TYPE_CHECKING:
    from pathlib import Path
    from sqlite3 import Connection, Row

_SNAPSHOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS achievement_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_data_version TEXT NOT NULL,
    source_generated_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    achievement_count INTEGER NOT NULL
)
"""
_ITEM_SCHEMA = """
CREATE TABLE IF NOT EXISTS achievement_snapshot_item (
    snapshot_id INTEGER NOT NULL,
    achievement_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    point INTEGER NOT NULL,
    description TEXT NOT NULL,
    is_hidden INTEGER NOT NULL,
    type_name TEXT NOT NULL,
    branch_name TEXT NOT NULL,
    title_name TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, achievement_id)
)
"""
_INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_achievement_snapshot_source
ON achievement_snapshot(source_generated_at, id)
"""
_MIGRATIONS = (
    SqliteMigration(1, (_SNAPSHOT_SCHEMA, _ITEM_SCHEMA, _INDEX_SCHEMA)),
)


class SqliteAchievementHistoryStore:
    def __init__(
        self,
        path: str | Path,
        *,
        max_snapshots: int,
        baseline_lookback_days: int = 4,
    ) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            row_factory=sqlite3.Row,
        )
        self._max_snapshots = max(2, max_snapshots)
        self._baseline_lookback_days = max(1, baseline_lookback_days)

    def record(self, snapshot: AchievementSnapshot) -> bool:
        with self._database.connect() as connection:
            latest = connection.execute(
                """
                SELECT id, game_data_version, source_generated_at, content_hash
                FROM achievement_snapshot
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            if latest is not None:
                same_version = (
                    str(latest["game_data_version"])
                    == snapshot.game_data_version
                )
                same_content = str(latest["content_hash"]) == snapshot.content_hash
                if same_version and same_content:
                    return False
                if same_version:
                    self._replace_latest(
                        connection,
                        snapshot_id=int(latest["id"]),
                        snapshot=snapshot,
                    )
                    return True

            cursor = connection.execute(
                """
                INSERT INTO achievement_snapshot (
                    game_data_version,
                    source_generated_at,
                    observed_at,
                    content_hash,
                    achievement_count
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot.game_data_version,
                    snapshot.source_generated_at.isoformat(),
                    snapshot.observed_at.isoformat(),
                    snapshot.content_hash,
                    len(snapshot.achievements),
                ),
            )
            assert cursor.lastrowid is not None
            snapshot_id = int(cursor.lastrowid)
            self._insert_items(connection, snapshot_id, snapshot)
            self._prune(connection)
        return True

    def compare_latest(self) -> AchievementComparison | None:
        with self._database.connect() as connection:
            current_row = connection.execute(
                """
                SELECT
                    id,
                    game_data_version,
                    source_generated_at,
                    observed_at,
                    achievement_count
                FROM achievement_snapshot
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            if current_row is None:
                return None
            history_rows = connection.execute(
                """
                SELECT
                    id,
                    game_data_version,
                    source_generated_at,
                    observed_at,
                    achievement_count
                FROM achievement_snapshot
                WHERE id < ?
                ORDER BY id DESC
                """,
                (int(current_row["id"]),),
            ).fetchall()
            current = _snapshot_version(current_row)
            baseline_rows = _select_baseline_rows(
                current_row,
                history_rows,
                lookback_days=self._baseline_lookback_days,
            )
            if not baseline_rows:
                return AchievementComparison(current=current, baseline=None, added=())
            baseline = _snapshot_version(baseline_rows[0])
            added_by_id: dict[int, AchievementRecord] = {}
            for baseline_row in baseline_rows:
                baseline_version = _snapshot_version(baseline_row)
                added_rows = _load_added_rows(
                    connection,
                    current_snapshot_id=current.snapshot_id,
                    baseline_snapshot_id=baseline_version.snapshot_id,
                )
                for row in added_rows:
                    achievement = _achievement_record(row)
                    added_by_id.setdefault(
                        achievement.achievement_id,
                        achievement,
                    )
        return AchievementComparison(
            current=current,
            baseline=baseline,
            added=tuple(
                added_by_id[achievement_id]
                for achievement_id in sorted(added_by_id)
            ),
        )

    def _replace_latest(
        self,
        connection: Connection,
        *,
        snapshot_id: int,
        snapshot: AchievementSnapshot,
    ) -> None:
        connection.execute(
            """
            UPDATE achievement_snapshot
            SET source_generated_at = ?,
                observed_at = ?,
                content_hash = ?,
                achievement_count = ?
            WHERE id = ?
            """,
            (
                snapshot.source_generated_at.isoformat(),
                snapshot.observed_at.isoformat(),
                snapshot.content_hash,
                len(snapshot.achievements),
                snapshot_id,
            ),
        )
        connection.execute(
            "DELETE FROM achievement_snapshot_item WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        self._insert_items(connection, snapshot_id, snapshot)

    @staticmethod
    def _insert_items(
        connection: Connection,
        snapshot_id: int,
        snapshot: AchievementSnapshot,
    ) -> None:
        connection.executemany(
            """
            INSERT INTO achievement_snapshot_item (
                snapshot_id,
                achievement_id,
                name,
                point,
                description,
                is_hidden,
                type_name,
                branch_name,
                title_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    snapshot_id,
                    item.achievement_id,
                    item.name,
                    item.point,
                    item.description,
                    int(item.is_hidden),
                    item.type_name,
                    item.branch_name,
                    item.title_name,
                )
                for item in snapshot.achievements
            ),
        )

    def _prune(self, connection: Connection) -> None:
        stale_rows = connection.execute(
            """
            SELECT id
            FROM achievement_snapshot
            ORDER BY id DESC
            LIMIT -1 OFFSET ?
            """,
            (self._max_snapshots,),
        ).fetchall()
        stale_ids = tuple(int(row["id"]) for row in stale_rows)
        if not stale_ids:
            return
        placeholders = ",".join("?" for _ in stale_ids)
        delete_items = (
            "DELETE FROM achievement_snapshot_item "
            f"WHERE snapshot_id IN ({placeholders})"
        )
        connection.execute(
            delete_items,
            stale_ids,
        )
        connection.execute(
            f"DELETE FROM achievement_snapshot WHERE id IN ({placeholders})",
            stale_ids,
        )


def _snapshot_version(row: Row) -> AchievementSnapshotVersion:
    return AchievementSnapshotVersion(
        snapshot_id=int(row["id"]),
        game_data_version=str(row["game_data_version"]),
        source_generated_at=datetime.fromisoformat(str(row["source_generated_at"])),
        observed_at=datetime.fromisoformat(str(row["observed_at"])),
        achievement_count=int(row["achievement_count"]),
    )


def _achievement_record(row: Row) -> AchievementRecord:
    return AchievementRecord(
        achievement_id=int(row["achievement_id"]),
        name=str(row["name"]),
        point=int(row["point"]),
        description=str(row["description"]),
        is_hidden=bool(row["is_hidden"]),
        type_name=str(row["type_name"]),
        branch_name=str(row["branch_name"]),
        title_name=str(row["title_name"]),
    )


def _select_baseline_rows(
    current_row: Row,
    history_rows: list[Row],
    *,
    lookback_days: int,
) -> tuple[Row, ...]:
    current_time = _snapshot_effective_time(current_row)
    current_cycle = _nearest_friday(current_time)
    cutoff = current_time - timedelta(days=lookback_days)
    timed_rows = [
        (row, _snapshot_effective_time(row))
        for row in history_rows
    ]
    weekly_candidates = [
        (row, snapshot_time)
        for row, snapshot_time in timed_rows
        if _nearest_friday(snapshot_time) < current_cycle
    ]
    lookback_candidates = [
        (row, snapshot_time)
        for row, snapshot_time in timed_rows
        if snapshot_time <= cutoff
    ]
    selected: list[Row] = []
    selected_ids: set[int] = set()
    for candidates in (weekly_candidates, lookback_candidates):
        if not candidates:
            continue
        row = max(
            candidates,
            key=lambda item: (item[1], int(item[0]["id"])),
        )[0]
        row_id = int(row["id"])
        if row_id in selected_ids:
            continue
        selected.append(row)
        selected_ids.add(row_id)
    return tuple(selected)


def _load_added_rows(
    connection: Connection,
    *,
    current_snapshot_id: int,
    baseline_snapshot_id: int,
) -> list[Row]:
    return connection.execute(
        """
        SELECT
            current.achievement_id,
            current.name,
            current.point,
            current.description,
            current.is_hidden,
            current.type_name,
            current.branch_name,
            current.title_name
        FROM achievement_snapshot_item AS current
        LEFT JOIN achievement_snapshot_item AS baseline
          ON baseline.snapshot_id = ?
         AND (
                baseline.achievement_id = current.achievement_id
             OR (
                    baseline.name = current.name
                AND baseline.point = current.point
                AND baseline.description = current.description
                AND baseline.is_hidden = current.is_hidden
                AND baseline.type_name = current.type_name
                AND baseline.branch_name = current.branch_name
                AND baseline.title_name = current.title_name
             )
         )
        WHERE current.snapshot_id = ?
          AND baseline.achievement_id IS NULL
        ORDER BY current.achievement_id
        """,
        (baseline_snapshot_id, current_snapshot_id),
    ).fetchall()


def _snapshot_effective_time(row: Row) -> datetime:
    version = str(row["game_data_version"]).strip()
    for date_format in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"):
        try:
            parsed = datetime.strptime(version, date_format).replace(tzinfo=TZ_CN)
        except ValueError:
            continue
        return parsed.astimezone(timezone.utc)

    generated_at = datetime.fromisoformat(str(row["source_generated_at"]))
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    return generated_at.astimezone(timezone.utc)


def _nearest_friday(value: datetime) -> date:
    local_date = value.astimezone(TZ_CN).date()
    previous = local_date - timedelta(days=(local_date.weekday() - 4) % 7)
    following = previous + timedelta(days=7)
    return (
        previous
        if (local_date - previous) <= (following - local_date)
        else following
    )
