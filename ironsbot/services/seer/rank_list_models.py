# SPDX-License-Identifier: GPL-3.0-or-later
from dataclasses import dataclass

from ironsbot.services.seer.rank_constants import (
    ACHIEVE_RANK_KEY,
    ACHIEVE_RANK_SUB_KEY,
    AUTOCARD_RANK_KEY,
    AUTOCARD_RANK_SUB_KEY,
    BOOK_RANK_KEY,
    BOOK_RANK_SUB_KEY,
    COUNTERMARK_RANK_KEY,
    COUNTERMARK_RANK_SUB_KEY,
    EXPERT_PEAK_USER_RANK_KEY,
    MOUNT_RANK_SUB_KEY,
    OUTFIT_PART_RANK_SUB_KEY,
    OUTFIT_RANK_KEY,
    OUTFIT_SUIT_RANK_SUB_KEY,
    PET_KIND_RANK_KEY,
    PET_KIND_RANK_SUB_KEY,
    SKIN_RANK_KEY,
    SKIN_RANK_SUB_KEY,
    STANDARD_PEAK_USER_RANK_KEY,
    WILD_PEAK_USER_RANK_KEY,
)

RANK_LIST_SIZE = 10
RANK_LIST_MAX_SIZE = 100
BATCH_CACHE_PREFIXES = ("缓存榜单", "批量缓存榜单", "缓存排行", "批量缓存排行")
RANK_PAGE_CACHE_STATUS_PREFIXES = (
    "榜单情况",
    "榜单状态",
)
RANK_PAGE_CACHE_REFRESH_PREFIXES = (
    "刷新榜单",
)
MAX_CACHE_INTERVALS_SHOWN = 20


@dataclass(frozen=True, slots=True)
class GlobalRankSpec:
    title: str
    key: int
    sub_key: int
    unit: str
    peak_season_sub_key: bool = False
    score_format: str = ""


@dataclass(frozen=True, slots=True)
class LocalRankSpec:
    title: str
    metric_key: str
    season_limited: bool = False


@dataclass(frozen=True, slots=True)
class RankListCommand:
    kind: str
    rank_key: str
    start_rank: int = 1
    limit: int = RANK_LIST_SIZE


@dataclass(frozen=True, slots=True)
class RankScoreCommand:
    rank_key: str
    score: int


@dataclass(frozen=True, slots=True)
class RankPlayerCommand:
    rank_key: str
    player_id: int


@dataclass(frozen=True, slots=True)
class RankCacheBatchCommand:
    rank_key: str
    start_rank: int
    end_rank: int


@dataclass(frozen=True, slots=True)
class RankPageCacheStatusCommand:
    rank_key: str


@dataclass(frozen=True, slots=True)
class RankPageCacheRefreshCommand:
    rank_key: str | None = None


GLOBAL_RANKS: dict[str, GlobalRankSpec] = {
    "图鉴积分": GlobalRankSpec("图鉴积分榜", BOOK_RANK_KEY, BOOK_RANK_SUB_KEY, "分"),
    "成就点数": GlobalRankSpec(
        "成就点数榜", ACHIEVE_RANK_KEY, ACHIEVE_RANK_SUB_KEY, "点"
    ),
    "精灵图鉴": GlobalRankSpec(
        "精灵图鉴榜",
        PET_KIND_RANK_KEY,
        PET_KIND_RANK_SUB_KEY,
        "项",
    ),
    "皮肤图鉴": GlobalRankSpec("皮肤图鉴榜", SKIN_RANK_KEY, SKIN_RANK_SUB_KEY, "款"),
    "套装图鉴": GlobalRankSpec(
        "套装图鉴榜", OUTFIT_RANK_KEY, OUTFIT_SUIT_RANK_SUB_KEY, "套"
    ),
    "部件图鉴": GlobalRankSpec(
        "部件图鉴榜", OUTFIT_RANK_KEY, OUTFIT_PART_RANK_SUB_KEY, "件"
    ),
    "座驾图鉴": GlobalRankSpec("座驾图鉴榜", OUTFIT_RANK_KEY, MOUNT_RANK_SUB_KEY, "个"),
    "刻印图鉴": GlobalRankSpec(
        "刻印图鉴榜", COUNTERMARK_RANK_KEY, COUNTERMARK_RANK_SUB_KEY, "枚"
    ),
    "群星牌": GlobalRankSpec(
        "群星之巅榜", AUTOCARD_RANK_KEY, AUTOCARD_RANK_SUB_KEY, "分"
    ),
    "竞技段位": GlobalRankSpec(
        "竞技段位榜",
        STANDARD_PEAK_USER_RANK_KEY,
        0,
        "分",
        peak_season_sub_key=True,
        score_format="peak_rating",
    ),
    "狂野段位": GlobalRankSpec(
        "狂野段位榜",
        WILD_PEAK_USER_RANK_KEY,
        0,
        "分",
        peak_season_sub_key=True,
        score_format="peak_rating",
    ),
    "专家段位": GlobalRankSpec(
        "专家段位榜",
        EXPERT_PEAK_USER_RANK_KEY,
        0,
        "分",
        peak_season_sub_key=True,
    ),
}

LOCAL_RANKS: dict[str, LocalRankSpec] = {
    "图鉴积分": LocalRankSpec("样本图鉴积分榜", "book_score"),
    "成就点数": LocalRankSpec("样本成就点数榜", "achievement_score"),
    "精灵数量": LocalRankSpec("样本精灵总数榜", "pet_total_count"),
    "精灵图鉴": LocalRankSpec("样本精灵图鉴榜", "pet_kind_count"),
    "皮肤图鉴": LocalRankSpec("样本皮肤图鉴榜", "skin_count"),
    "套装图鉴": LocalRankSpec("样本套装图鉴榜", "outfit_suit_count"),
    "部件图鉴": LocalRankSpec("样本部件图鉴榜", "outfit_part_count"),
    "座驾图鉴": LocalRankSpec("样本座驾图鉴榜", "mount_count"),
    "刻印图鉴": LocalRankSpec("样本刻印图鉴榜", "countermark_count"),
    "群星牌": LocalRankSpec("样本群星牌积分榜", "autocard_score"),
    "已解锁图鉴": LocalRankSpec("样本已解锁图鉴榜", "unlocked_book_entries"),
    "成就数量": LocalRankSpec("样本成就数量榜", "achievement_count"),
    "竞技段位": LocalRankSpec(
        "样本竞技段位榜", "peak_standard", season_limited=True
    ),
    "竞技胜率": LocalRankSpec(
        "样本竞技胜率榜", "peak_standard_win_rate", season_limited=True
    ),
    "竞技场次": LocalRankSpec(
        "样本竞技场次榜", "peak_standard_matches", season_limited=True
    ),
    "狂野段位": LocalRankSpec("样本狂野段位榜", "peak_wild", season_limited=True),
    "狂野胜率": LocalRankSpec(
        "样本狂野胜率榜", "peak_wild_win_rate", season_limited=True
    ),
    "狂野场次": LocalRankSpec(
        "样本狂野场次榜", "peak_wild_matches", season_limited=True
    ),
    "专家段位": LocalRankSpec("样本专家段位榜", "peak_expert", season_limited=True),
    "专家胜率": LocalRankSpec(
        "样本专家胜率榜", "peak_expert_win_rate", season_limited=True
    ),
    "专家场次": LocalRankSpec(
        "样本专家场次榜", "peak_expert_matches", season_limited=True
    ),
    "巅峰总场次": LocalRankSpec(
        "样本巅峰总场次榜", "peak_total_matches", season_limited=True
    ),
}
