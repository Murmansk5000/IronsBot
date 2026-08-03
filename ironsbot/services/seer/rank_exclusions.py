# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.rank_exclusions import (
    DEFAULT_RANK_EXCLUSION_USER_IDS_BY_RANK,
    DEFAULT_TAOMEE_INTERNAL_USER_IDS,
    RANK_EXCLUSION_CONFIG_KEY_BY_RANK,
)
from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS, GlobalRankSpec

if TYPE_CHECKING:
    from ironsbot.config.models.seer import RankExclusionConfig


@dataclass(frozen=True, slots=True)
class RankExclusionPolicy:
    """Derive public-rank and local-sample eligibility from one config source."""

    taomee_internal_user_ids: frozenset[int]
    user_ids_by_rank: dict[str, frozenset[int]]

    @classmethod
    def from_config(
        cls,
        config: RankExclusionConfig | None = None,
    ) -> RankExclusionPolicy:
        if config is None:
            taomee_ids = DEFAULT_TAOMEE_INTERNAL_USER_IDS
            configured = DEFAULT_RANK_EXCLUSION_USER_IDS_BY_RANK
        else:
            taomee_ids = config.taomee_internal_user_ids
            configured = config.user_ids_by_rank
        return cls(
            taomee_internal_user_ids=frozenset(taomee_ids),
            user_ids_by_rank={
                rank_key: frozenset(user_ids)
                for rank_key, user_ids in configured.items()
            },
        )

    def excludes_from_sample(self, user_id: int) -> bool:
        return user_id in self.taomee_internal_user_ids

    def excluded_user_ids(self, rank_key: str | None) -> frozenset[int]:
        if rank_key is None:
            return self.taomee_internal_user_ids
        config_key = RANK_EXCLUSION_CONFIG_KEY_BY_RANK.get(rank_key, rank_key)
        return self.taomee_internal_user_ids.union(
            self.user_ids_by_rank.get(config_key, frozenset())
        )

    def excludes_from_public_rank(self, rank_key: str | None, user_id: int) -> bool:
        return user_id in self.excluded_user_ids(rank_key)

    def rank_key_for_protocol(self, *, key: int, sub_key: int) -> str | None:
        for rank_key, spec in GLOBAL_RANKS.items():
            if spec.key != key:
                continue
            if spec.peak_season_sub_key or spec.sub_key == sub_key:
                return rank_key
        return None

    def excludes_spec(self, spec: GlobalRankSpec, user_id: int) -> bool:
        for rank_key, candidate in GLOBAL_RANKS.items():
            if candidate == spec:
                return self.excludes_from_public_rank(rank_key, user_id)
        return user_id in self.taomee_internal_user_ids
