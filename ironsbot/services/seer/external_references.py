# SPDX-License-Identifier: MIT
"""Central SeerInfo companion-link registry."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.config.models.seer import ExternalReferencesConfig


class SeerInfoReference(str, Enum):
    PLAYER_QUERY = "player_query"
    TEAM_QUERY = "team_query"
    SERVER_STATUS = "server_status"
    WEEKLY_PREVIEW = "weekly_preview"
    BILIBILI_HISTORY = "bilibili_history"
    PEAK_POOL = "peak_pool"
    PEAK_MASTER_POOL = "peak_master_pool"
    PEAK_VOTE = "peak_vote"
    PEAK_STANDARD_PLAYER_RANK = "peak_standard_player_rank"
    PEAK_WILD_PLAYER_RANK = "peak_wild_player_rank"
    PEAK_EXPERT_PLAYER_RANK = "peak_expert_player_rank"
    PEAK_STANDARD_SUIT_RANK = "peak_standard_suit_rank"
    PEAK_WILD_SUIT_RANK = "peak_wild_suit_rank"
    PEAK_EXPERT_SUIT_RANK = "peak_expert_suit_rank"
    PEAK_STANDARD_TITLE_RANK = "peak_standard_title_rank"
    PEAK_WILD_TITLE_RANK = "peak_wild_title_rank"
    PEAK_EXPERT_TITLE_RANK = "peak_expert_title_rank"
    PEAK_STANDARD_PET_RANK = "peak_standard_pet_rank"
    PEAK_WILD_PET_RANK = "peak_wild_pet_rank"
    PEAK_EXPERT_PET_RANK = "peak_expert_pet_rank"


_BASE_URL = "https://seerinfo.yuyuqaq.cn"
_URLS: dict[SeerInfoReference, str] = {
    SeerInfoReference.PLAYER_QUERY: f"{_BASE_URL}/query",
    SeerInfoReference.TEAM_QUERY: f"{_BASE_URL}/query",
    SeerInfoReference.SERVER_STATUS: f"{_BASE_URL}/query",
    SeerInfoReference.WEEKLY_PREVIEW: f"{_BASE_URL}/preview",
    SeerInfoReference.BILIBILI_HISTORY: f"{_BASE_URL}/bilibili",
    SeerInfoReference.PEAK_POOL: f"{_BASE_URL}/peak/pvpban",
    SeerInfoReference.PEAK_MASTER_POOL: f"{_BASE_URL}/peak/pvpcostmode",
    SeerInfoReference.PEAK_VOTE: f"{_BASE_URL}/peak/pvpvote",
}


def _peak_urls() -> dict[SeerInfoReference, str]:
    result: dict[SeerInfoReference, str] = {}
    for mode, prefix in (
        ("sports", "STANDARD"),
        ("wild", "WILD"),
        ("expert", "EXPERT"),
    ):
        for category, suffix in (
            ("player", "PLAYER_RANK"),
            ("suit", "SUIT_RANK"),
            ("title", "TITLE_RANK"),
            ("monster", "PET_RANK"),
        ):
            reference = SeerInfoReference[f"PEAK_{prefix}_{suffix}"]
            result[reference] = f"{_BASE_URL}/peak/pvprank/{mode}/{category}"
    return result


_URLS.update(_peak_urls())

_CONFIG_FIELDS: dict[SeerInfoReference, str] = {
    SeerInfoReference.PLAYER_QUERY: "player_query",
    SeerInfoReference.TEAM_QUERY: "team_query",
    SeerInfoReference.SERVER_STATUS: "server_status",
    SeerInfoReference.WEEKLY_PREVIEW: "weekly_preview",
    SeerInfoReference.BILIBILI_HISTORY: "bilibili_history",
    SeerInfoReference.PEAK_POOL: "peak_pool",
    SeerInfoReference.PEAK_MASTER_POOL: "peak_master_pool",
    SeerInfoReference.PEAK_VOTE: "peak_vote",
    **dict.fromkeys(
        (
            SeerInfoReference.PEAK_STANDARD_PLAYER_RANK,
            SeerInfoReference.PEAK_WILD_PLAYER_RANK,
            SeerInfoReference.PEAK_EXPERT_PLAYER_RANK,
        ),
        "peak_player_rank",
    ),
    **dict.fromkeys(
        (
            SeerInfoReference.PEAK_STANDARD_SUIT_RANK,
            SeerInfoReference.PEAK_WILD_SUIT_RANK,
            SeerInfoReference.PEAK_EXPERT_SUIT_RANK,
        ),
        "peak_suit_rank",
    ),
    **dict.fromkeys(
        (
            SeerInfoReference.PEAK_STANDARD_TITLE_RANK,
            SeerInfoReference.PEAK_WILD_TITLE_RANK,
            SeerInfoReference.PEAK_EXPERT_TITLE_RANK,
        ),
        "peak_title_rank",
    ),
    **dict.fromkeys(
        (
            SeerInfoReference.PEAK_STANDARD_PET_RANK,
            SeerInfoReference.PEAK_WILD_PET_RANK,
            SeerInfoReference.PEAK_EXPERT_PET_RANK,
        ),
        "peak_pet_rank",
    ),
}


class SeerInfoReferences:
    def __init__(self, config: ExternalReferencesConfig) -> None:
        self._config = config

    def url_for(self, reference: SeerInfoReference | None) -> str:
        if reference is None:
            return ""
        if not getattr(self._config, _CONFIG_FIELDS[reference]):
            return ""
        return _URLS[reference]

    def append(self, text: str, reference: SeerInfoReference | None) -> str:
        url = self.url_for(reference)
        return text if not url else f"{text}\n\n相关查询：{url}"


def peak_rank_reference(
    *,
    peak_type: int,
    category: str,
) -> SeerInfoReference:
    mode = {1: "STANDARD", 2: "WILD", 3: "EXPERT"}[peak_type]
    suffix = {
        "player": "PLAYER_RANK",
        "suit": "SUIT_RANK",
        "title": "TITLE_RANK",
        "pet": "PET_RANK",
    }[category]
    return SeerInfoReference[f"PEAK_{mode}_{suffix}"]
