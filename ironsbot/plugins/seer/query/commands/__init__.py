# SPDX-License-Identifier: GPL-3.0-or-later

from ..group import SeerMatcherGroup
from . import (
    autocard,
    countermark_stat_rank,
    data_queries,
    equipment_queries,
    mintmark_queries,
    peak_queries,
    pet_queries,
    player,
    player_shortcuts,
    rank_list,
    team,
    type_queries,
)


def install(group: SeerMatcherGroup) -> None:
    autocard.install(group)
    countermark_stat_rank.install(group)
    data_queries.install(group)
    equipment_queries.install(group)
    mintmark_queries.install(group)
    peak_queries.install(group)
    pet_queries.install(group)
    player.install(group)
    player_shortcuts.install(group)
    rank_list.install(group)
    team.install(group)
    type_queries.install(group)


__all__ = ["install"]
