# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.rank_list_formatting import format_rank_window, now_text
from ironsbot.services.seer.rank_list_models import RANK_LIST_SIZE, LocalRankSpec

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any


def format_local_rank_message(  # noqa: PLR0913
    spec: LocalRankSpec,
    entries: Sequence[Any],
    *,
    sample_count: int,
    timestamp: str | None = None,
    season_sub_key: str | None = None,
    start_rank: int = 1,
    requested_count: int = RANK_LIST_SIZE,
) -> str:
    if not entries:
        return f"❌暂无{spec.title}数据。先查询一些米米号后再试。"

    range_text = format_rank_window(start_rank, len(entries), requested_count)
    if range_text:
        title = (
            f"{spec.title}（{range_text}，样本{sample_count}人，"
            f"截至{timestamp or now_text()}）"
        )
    else:
        title = f"{spec.title}（样本{sample_count}人，截至{timestamp or now_text()}）"
    if season_sub_key is not None:
        title += f"\n赛季样本：{season_sub_key}"

    lines = [title]
    lines.extend(
        f"{entry.rank}. {entry.nick}（{entry.user_id}） {entry.display}"
        for entry in entries
    )
    return "\n".join(lines)
