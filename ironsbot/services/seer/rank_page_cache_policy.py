# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

from ironsbot.config.loader import get_app_config
from ironsbot.services.seer.rank_page_cache_storage import (
    connect_rank_page_cache as _connect_storage,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from pathlib import Path

    from ironsbot.config.models.seer import RankQueryConfig


def get_rank_query_config() -> RankQueryConfig:
    return get_app_config().seer.rank


def rank_page_cache_path() -> Path:
    return get_rank_query_config().page_cache_path


@contextmanager
def connect_rank_page_cache() -> Iterator[sqlite3.Connection]:
    with _connect_storage(rank_page_cache_path()) as conn:
        yield conn


def rank_page_cache_enabled() -> bool:
    return get_rank_query_config().page_cache


def rank_page_cache_ttl_seconds() -> int:
    return get_rank_query_config().page_cache_ttl_seconds


def rank_page_cache_is_stale(fetched_at: float) -> bool:
    ttl = rank_page_cache_ttl_seconds()
    return ttl <= 0 or time.time() - fetched_at > ttl


def rank_page_cache_allows_stale(*, allow_stale: bool | None) -> bool:
    if allow_stale is None:
        return get_rank_query_config().allow_stale_cache
    return allow_stale
