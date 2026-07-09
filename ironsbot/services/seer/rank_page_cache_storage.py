# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.shared.sqlite import open_sqlite_schema

if TYPE_CHECKING:
    import sqlite3
    from contextlib import AbstractContextManager
    from pathlib import Path


RANK_PAGE_CACHE_SCHEMA = (
    """
        CREATE TABLE IF NOT EXISTS rank_players (
            user_id INTEGER PRIMARY KEY,
            nick TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL
        )
    """,
    """
        CREATE TABLE IF NOT EXISTS rank_pages (
            key INTEGER NOT NULL,
            sub_key INTEGER NOT NULL,
            start_index INTEGER NOT NULL,
            end_index INTEGER NOT NULL,
            page_size INTEGER NOT NULL,
            fetched_at REAL NOT NULL,
            expected_count INTEGER NOT NULL,
            actual_count INTEGER NOT NULL,
            PRIMARY KEY (key, sub_key, start_index, end_index)
        )
    """,
    """
        CREATE TABLE IF NOT EXISTS player_rank_facts (
            key INTEGER NOT NULL,
            sub_key INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            rank_index INTEGER NOT NULL,
            score INTEGER NOT NULL,
            display TEXT NOT NULL DEFAULT '',
            fetched_at REAL NOT NULL,
            source_start_index INTEGER NOT NULL,
            source_end_index INTEGER NOT NULL,
            PRIMARY KEY (key, sub_key, user_id),
            UNIQUE (key, sub_key, rank_index)
        )
    """,
    """
        CREATE INDEX IF NOT EXISTS idx_player_rank_facts_rank
        ON player_rank_facts (key, sub_key, rank_index)
    """,
    """
        CREATE INDEX IF NOT EXISTS idx_player_rank_facts_score
        ON player_rank_facts (key, sub_key, score DESC, rank_index)
    """,
)


def connect_rank_page_cache(path: Path) -> AbstractContextManager[sqlite3.Connection]:
    return open_sqlite_schema(path, RANK_PAGE_CACHE_SCHEMA)


def ensure_rank_page_cache_schema(conn: sqlite3.Connection) -> None:
    for statement in RANK_PAGE_CACHE_SCHEMA:
        conn.execute(statement)


__all__ = [
    "connect_rank_page_cache",
    "ensure_rank_page_cache_schema",
]
