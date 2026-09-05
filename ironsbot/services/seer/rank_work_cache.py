# SPDX-License-Identifier: GPL-3.0-or-later
"""Record cached and live rank-page query work."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.query_work import (
    record_cached_query_work,
    record_successful_query_work,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.rank_exclusions import RankExclusionPolicy


def record_rank_page_work(
    policy: RankExclusionPolicy,
    *,
    key: int,
    sub_key: int,
    cached: bool,
) -> None:
    rank_key = policy.rank_key_for_protocol(key=key, sub_key=sub_key)
    if rank_key is None:
        return
    work_unit = f"rank:{rank_key}"
    if cached:
        record_cached_query_work(work_unit)
    else:
        record_successful_query_work(work_unit)
