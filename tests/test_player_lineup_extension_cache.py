from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from ironsbot.extensions.contracts import PlayerLineupCachedReply
from ironsbot.extensions.player_lineup import PlayerLineupCacheServices

if TYPE_CHECKING:
    from pathlib import Path


def test_public_lineup_cache_round_trips_completed_reply(tmp_path: Path) -> None:
    cache = PlayerLineupCacheServices(now=lambda: 1000.0).open(
        str(tmp_path / "lineup.sqlite")
    )
    reply = PlayerLineupCachedReply(
        leading_text="玩家信息\n",
        text="",
        image=b"lineup-image",
        fetched_at=990.0,
    )

    cache.put(105023264, reply)

    assert cache.get(105023264) == reply
    assert cache.get(1) is None


def test_cache_expires_from_source_time_without_renewing(tmp_path: Path) -> None:
    now = [1000.0]
    cache = PlayerLineupCacheServices(ttl_seconds=300, now=lambda: now[0]).open(
        str(tmp_path / "lineup.sqlite")
    )
    reply = PlayerLineupCachedReply(image=b"complete", fetched_at=990.0)
    cache.put(123456789, reply)
    now[0] = 1289.0
    assert cache.get(123456789) == reply
    now[0] = 1290.0
    assert cache.get(123456789) is None
    now[0] += 15 * 86400
    assert cache.get(123456789) is None


def test_old_undated_rows_are_migrated_without_inventing_freshness(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lineup.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE player_lineup_cache (player_id INTEGER PRIMARY KEY, "
            "leading_text TEXT NOT NULL, text TEXT NOT NULL, image BLOB, "
            "image_error TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO player_lineup_cache VALUES (?, ?, ?, ?, ?, ?)",
            (123456789, "old", "", b"old-image", "", "2026-10-16T00:00:00Z"),
        )
    cache = PlayerLineupCacheServices(now=lambda: 1000).open(str(path))
    assert cache.get(123456789) is None
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT fetched_at FROM player_lineup_cache"
        ).fetchone() == (None,)


def test_invalid_observations_do_not_replace_good_cache(tmp_path: Path) -> None:
    cache = PlayerLineupCacheServices(now=lambda: 1000).open(
        str(tmp_path / "lineup.sqlite")
    )
    good = PlayerLineupCachedReply(image=b"good", fetched_at=999)
    cache.put(123456789, good)
    for fetched_at in (None, float("nan"), float("inf"), 1001.0, -1.0):
        cache.put(
            123456789, PlayerLineupCachedReply(image=b"bad", fetched_at=fetched_at)
        )
        assert cache.get(123456789) == good
