# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import replace

from ironsbot.config.loader import get_app_config
from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS, GlobalRankSpec
from ironsbot.services.seer.rank_peak import get_current_peak_sub_key


def resolve_global_rank_spec(spec: GlobalRankSpec) -> GlobalRankSpec:
    if not spec.peak_season_sub_key:
        return spec

    sub_key = get_current_peak_sub_key(get_app_config().seer.rank.peak_subkey)
    if sub_key is None:
        return spec
    return replace(spec, sub_key=sub_key)


def global_rank_spec_needs_sub_key(spec: GlobalRankSpec) -> bool:
    return spec.peak_season_sub_key and spec.sub_key <= 0


def get_global_rank_spec(rank_key: str) -> GlobalRankSpec:
    return resolve_global_rank_spec(GLOBAL_RANKS[rank_key])


__all__ = [
    "get_global_rank_spec",
    "global_rank_spec_needs_sub_key",
    "resolve_global_rank_spec",
]
