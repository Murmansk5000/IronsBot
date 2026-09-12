# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ironsbot.integrations.seer_data.countermark_stat_rank_repository import (
    load_countermark_rank_data,
)
from ironsbot.services.seer.countermark_stat_rank_messages import (
    build_countermark_stat_rank_message,
)
from ironsbot.services.seer.countermark_stat_rank_models import (
    CountermarkStatRankDataError,
)
from ironsbot.services.seer.countermark_stat_rank_ranking import (
    collect_countermark_rank_items,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.countermark_stat_rank_models import (
        CountermarkStatRankCommand,
    )
    from ironsbot.services.seer.data import SeerDataAccess

MISSING_MINTMARK_QUALITY_MESSAGE = (
    "❌ 刻印角数数据不完整，暂时无法查询刻印数值榜。"
)
logger = logging.getLogger(__name__)


class CountermarkStatRankService:
    def __init__(self, data: SeerDataAccess) -> None:
        self._data = data

    def query(self, command: CountermarkStatRankCommand) -> str:
        try:
            with self._data.query(load_countermark_rank_data) as rank_data:
                quality_map, mintmarks = rank_data
                if command.angle_count is not None and not quality_map:
                    return MISSING_MINTMARK_QUALITY_MESSAGE
                items = collect_countermark_rank_items(
                    mintmarks,
                    command,
                    quality_map,
                )
        except CountermarkStatRankDataError:
            logger.exception("published mintmark quality data is unavailable")
            return MISSING_MINTMARK_QUALITY_MESSAGE
        return build_countermark_stat_rank_message(
            command,
            items,
        )
