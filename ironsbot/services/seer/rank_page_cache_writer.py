# SPDX-License-Identifier: GPL-3.0-or-later
import sqlite3
import time
from collections.abc import Sequence

from nonebot.log import logger

from ironsbot.services.seer.rank_page_cache_policy import (
    connect_rank_page_cache,
    rank_page_cache_enabled,
)


def save_rank_page(  # noqa: PLR0913
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
    items: Sequence[object],
    fetched_at: float | None = None,
) -> None:
    if not rank_page_cache_enabled():
        return

    fetched_at_value = time.time() if fetched_at is None else fetched_at
    normalized_items = [
        (
            start + position,
            int(getattr(item, "id", 0)),
            str(getattr(item, "nick", "")),
            int(getattr(item, "score", 0)),
        )
        for position, item in enumerate(items)
        if int(getattr(item, "id", 0)) > 0
    ]
    user_ids = [user_id for _rank_index, user_id, _nick, _score in normalized_items]
    expected_count = max(0, end - start + 1)
    actual_count = len(
        {user_id for _rank_index, user_id, _nick, _score in normalized_items}
    )

    try:
        with connect_rank_page_cache() as conn:
            overlapping_pages = conn.execute(
                """
                SELECT start_index, end_index
                FROM rank_pages
                WHERE key = ?
                  AND sub_key = ?
                  AND NOT (end_index < ? OR start_index > ?)
                """,
                (key, sub_key, start, end),
            ).fetchall()
            for old_start, old_end in overlapping_pages:
                conn.execute(
                    """
                    DELETE FROM player_rank_facts
                    WHERE key = ?
                      AND sub_key = ?
                      AND source_start_index = ?
                      AND source_end_index = ?
                    """,
                    (key, sub_key, old_start, old_end),
                )
                conn.execute(
                    """
                    DELETE FROM rank_pages
                    WHERE key = ?
                      AND sub_key = ?
                      AND start_index = ?
                      AND end_index = ?
                    """,
                    (key, sub_key, old_start, old_end),
                )
            conn.execute(
                """
                DELETE FROM player_rank_facts
                WHERE key = ?
                  AND sub_key = ?
                  AND rank_index BETWEEN ? AND ?
                """,
                (key, sub_key, start, end),
            )
            if user_ids:
                conn.executemany(
                    """
                    DELETE FROM player_rank_facts
                    WHERE key = ?
                      AND sub_key = ?
                      AND user_id = ?
                    """,
                    ((key, sub_key, user_id) for user_id in user_ids),
                )
            conn.execute(
                """
                INSERT INTO rank_pages (
                    key, sub_key, start_index, end_index,
                    page_size, fetched_at, expected_count, actual_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key, sub_key, start_index, end_index) DO UPDATE SET
                    page_size = excluded.page_size,
                    fetched_at = excluded.fetched_at,
                    expected_count = excluded.expected_count,
                    actual_count = excluded.actual_count
                """,
                (
                    key,
                    sub_key,
                    start,
                    end,
                    expected_count,
                    fetched_at_value,
                    expected_count,
                    actual_count,
                ),
            )
            conn.executemany(
                """
                INSERT INTO rank_players (user_id, nick, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    nick = excluded.nick,
                    updated_at = excluded.updated_at
                """,
                [
                    (user_id, nick, fetched_at_value)
                    for _rank_index, user_id, nick, _score in normalized_items
                ],
            )
            conn.executemany(
                """
                INSERT INTO player_rank_facts (
                    key, sub_key, user_id, rank_index, score, display, fetched_at,
                    source_start_index, source_end_index
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key, sub_key, user_id) DO UPDATE SET
                    rank_index = excluded.rank_index,
                    score = excluded.score,
                    display = excluded.display,
                    fetched_at = excluded.fetched_at,
                    source_start_index = excluded.source_start_index,
                    source_end_index = excluded.source_end_index
                """,
                [
                    (
                        key,
                        sub_key,
                        user_id,
                        rank_index,
                        score,
                        nick,
                        fetched_at_value,
                        start,
                        end,
                    )
                    for rank_index, user_id, nick, score in normalized_items
                ],
            )
    except sqlite3.Error as e:
        logger.warning(f"failed to write Seer rank page cache: {e}")
