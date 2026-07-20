# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.countermark_stat_rank_messages import (
    build_countermark_stat_rank_message,
)
from ironsbot.services.seer.countermark_stat_rank_parsing import (
    parse_countermark_stat_rank_command,
)
from ironsbot.services.seer.countermark_stat_rank_ranking import (
    collect_countermark_rank_items,
)
from ironsbot.services.seer.countermark_stat_rank_repository import (
    MISSING_MINTMARK_QUALITY_MESSAGE,
    load_countermark_rank_data,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.countermark_stat_rank_models import (
        CountermarkStatRankCommand,
    )
    from ironsbot.services.seer.data import SeerDataAccess


class CountermarkStatRankService:
    def __init__(self, data: SeerDataAccess) -> None:
        self._data = data

    @staticmethod
    def parse_command(text: str) -> CountermarkStatRankCommand | None:
        return parse_countermark_stat_rank_command(text)

    def query(self, command: CountermarkStatRankCommand) -> str:
        with self._data.query(load_countermark_rank_data) as rank_data:
            quality_map, mintmarks = rank_data
            if command.angle_count is not None and not quality_map:
                return MISSING_MINTMARK_QUALITY_MESSAGE
            items = collect_countermark_rank_items(
                mintmarks,
                command,
                quality_map,
            )
        return build_countermark_stat_rank_message(
            command,
            items,
        )
