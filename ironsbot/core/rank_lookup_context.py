# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-request context shared by rank lookup services and the game adapter."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RankPagePolicy:
    phase: str = "search"
    priority: int = 1
    timeout: float | None = None
    retries: int | None = None
    parallel: bool = False


rank_page_policy: ContextVar[RankPagePolicy | None] = ContextVar(
    "rank_page_policy", default=None
)

rank_page_request_timeout: ContextVar[float | None] = ContextVar(
    "rank_page_request_timeout",
    default=None,
)
