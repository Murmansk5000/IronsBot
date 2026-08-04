# SPDX-License-Identifier: MIT
from __future__ import annotations

from .countermark_stat_rank_parsing import (
    parse_countermark_stat_rank_command,
)
from .rank_list_parsing import parse_rank_list_command


def is_rank_query_text(text: str) -> bool:
    """Return whether text should be handled by rank commands, not fuzzy lookup."""
    if parse_rank_list_command(text) is not None:
        return True

    return parse_countermark_stat_rank_command(text) is not None
