# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-request context shared by rank lookup services and the game adapter."""

from __future__ import annotations

from contextvars import ContextVar

rank_page_request_timeout: ContextVar[float | None] = ContextVar(
    "rank_page_request_timeout",
    default=None,
)
