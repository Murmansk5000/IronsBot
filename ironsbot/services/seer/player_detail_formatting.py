# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.player_collection_formatting import (
    format_autocard_rank_info,
    format_collection_info,
)
from ironsbot.services.seer.player_formatting_common import format_player_identity
from ironsbot.services.seer.player_peak_formatting import format_compact_peak_section
from ironsbot.services.seer.player_query import PlayerDetailMessages

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank_models import LocalRankSummary
    from ironsbot.services.seer.rank_models import (
        PeakSeasonRankSummary,
        PlayerRankSummary,
        RankLookupResult,
    )
    from ironsbot.services.seer.sequ_extra import (
        UnityPartOneInfo,
        UnityPeakInfo,
    )

def format_player_detail_messages(  # noqa: PLR0913
    *,
    player_id: int,
    user_info: Any,
    more_info: Any,
    unity_part_one: UnityPartOneInfo,
    unity_peak: UnityPeakInfo,
    rank_summary: PlayerRankSummary,
    peak_rank_summary: PeakSeasonRankSummary,
    autocard_rank_summary: RankLookupResult,
    local_rank_summary: LocalRankSummary,
    empty_local_rank_summary: LocalRankSummary,
    has_collection: bool,
    needs_peak_section: bool,
    has_autocard_rank: bool,
    show_local_rank: bool,
    extra_errors: list[str],
) -> PlayerDetailMessages:
    visible_local_rank_summary = (
        local_rank_summary if show_local_rank else empty_local_rank_summary
    )
    collection_message = (
        format_collection_info(
            more_info,
            unity_part_one=unity_part_one,
            rank_summary=rank_summary,
            local_summary=visible_local_rank_summary,
            player_identity=format_player_identity(player_id, user_info.nick),
        )
        if has_collection
        else ""
    )
    peak_message = (
        format_compact_peak_section(
            unity_peak,
            peak_rank_summary,
            visible_local_rank_summary,
            player_id=player_id,
            nick=user_info.nick,
        )
        if needs_peak_section
        else ""
    )
    autocard_message = (
        format_autocard_rank_info(
            autocard_rank_summary,
            player_identity=format_player_identity(player_id, user_info.nick),
            local_summary=local_rank_summary,
        )
        if has_autocard_rank
        else ""
    )
    return PlayerDetailMessages(
        collection_message=append_extra_errors(collection_message, extra_errors)
        if collection_message
        else "",
        peak_message=append_extra_errors(peak_message, extra_errors)
        if peak_message
        else "",
        autocard_message=append_extra_errors(autocard_message, extra_errors)
        if autocard_message
        else "",
    )


def append_extra_errors(message: str, extra_errors: list[str]) -> str:
    if not extra_errors:
        return message

    return "\n\n".join((message, "【扩展数据提示】", "；".join(extra_errors)))
