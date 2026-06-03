# SPDX-License-Identifier: GPL-3.0-or-later
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ironsbot.plugins.headless_seer.command_id import COMMAND_ID
from ironsbot.plugins.headless_seer.packets.peak import DailyRankParam

from ..config import plugin_config

BOOK_RANK_KEY = 156
BOOK_RANK_SUB_KEY = 1
ACHIEVE_RANK_KEY = 17
ACHIEVE_RANK_SUB_KEY = 0

PET_KIND_RANK_KEY = 158
PET_KIND_RANK_SUB_KEY = 1
COUNTERMARK_RANK_KEY = 159
COUNTERMARK_RANK_SUB_KEY = 1
OUTFIT_RANK_KEY = 160
OUTFIT_SUIT_RANK_SUB_KEY = 1
OUTFIT_PART_RANK_SUB_KEY = 2
MOUNT_RANK_SUB_KEY = 3
SKIN_RANK_KEY = 161
SKIN_RANK_SUB_KEY = 1

STANDARD_PEAK_USER_RANK_KEY = 120
WILD_PEAK_USER_RANK_KEY = 182
EXPERT_PEAK_USER_RANK_KEY = 199

ACHIEVE_SCORE_SEARCH_LIMIT = 30_000_000
BOOK_BREAKDOWN_SCAN_LIMIT = 2_000
PEAK_USER_SCORE_SEARCH_LIMIT = 100_000
PET_KIND_RANK_ANOMALY_USER_IDS = frozenset(
    (
        389438787,
        563101901,
        75576625,
        941831079,
        129030222,
        569440141,
        962351895,
        141312889,
        674021793,
        163443467,
        206601225,
        925171143,
        810989428,
        963527044,
        961510772,
        914692158,
        962236717,
        960755946,
        930395179,
        964791989,
        960957048,
        963833963,
        963123185,
        963190850,
        960351788,
        964035946,
        963236961,
        962883553,
        961625369,
        961392272,
        51010611,
    )
)
PET_KIND_RANK_ANOMALY_COUNT = len(PET_KIND_RANK_ANOMALY_USER_IDS)


def is_pet_kind_rank_anomaly_user(user_id: int) -> bool:
    return user_id in PET_KIND_RANK_ANOMALY_USER_IDS


@dataclass(slots=True)
class RankLookupResult:
    title: str
    score_name: str
    rank: int | None = None
    score: int | None = None
    searched_limit: int = 0
    queried: bool = False


@dataclass(slots=True)
class BookBreakdownSummary:
    pet_kind_count: int = 0
    pet_kind: RankLookupResult | None = None
    skin: RankLookupResult | None = None
    countermark: RankLookupResult | None = None
    outfit_suit: RankLookupResult | None = None
    outfit_part: RankLookupResult | None = None
    mount: RankLookupResult | None = None

    @classmethod
    def empty(cls) -> "BookBreakdownSummary":
        return cls(
            pet_kind=RankLookupResult(title="精灵图鉴", score_name="精灵"),
            skin=RankLookupResult(title="皮肤图鉴", score_name="皮肤"),
            countermark=RankLookupResult(title="刻印图鉴", score_name="刻印"),
            outfit_suit=RankLookupResult(title="套装图鉴", score_name="套装"),
            outfit_part=RankLookupResult(title="部件图鉴", score_name="部件"),
            mount=RankLookupResult(title="座驾图鉴", score_name="座驾"),
        )

    @property
    def outfit_count(self) -> int | None:
        scores = (
            None if self.outfit_suit is None else self.outfit_suit.score,
            None if self.outfit_part is None else self.outfit_part.score,
        )
        if any(score is None for score in scores):
            return None
        return int(scores[0]) + int(scores[1])

    @property
    def unlocked_count(self) -> int | None:
        scores = (
            self.pet_kind_count,
            None if self.skin is None else self.skin.score,
            None if self.countermark is None else self.countermark.score,
            self.outfit_count,
            None if self.mount is None else self.mount.score,
        )
        if any(score is None for score in scores):
            return None
        return sum(int(score) for score in scores)


@dataclass(slots=True)
class PlayerRankSummary:
    book: RankLookupResult
    achieve: RankLookupResult
    breakdown: BookBreakdownSummary

    @classmethod
    def empty(cls) -> "PlayerRankSummary":
        return cls(
            book=RankLookupResult(title="图鉴积分", score_name="图鉴积分"),
            achieve=RankLookupResult(title="成就点数", score_name="成就点数"),
            breakdown=BookBreakdownSummary.empty(),
        )


@dataclass(slots=True)
class PeakSeasonRankSummary:
    standard: RankLookupResult
    wild: RankLookupResult
    expert: RankLookupResult

    @classmethod
    def empty(cls) -> "PeakSeasonRankSummary":
        return cls(
            standard=RankLookupResult(title="竞技赛季榜", score_name="段位分"),
            wild=RankLookupResult(title="狂野赛季榜", score_name="段位分"),
            expert=RankLookupResult(title="专家赛季榜", score_name="专家积分"),
        )


async def _fetch_rank_page(
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
) -> list[Any]:
    _head, rank_list = await game.send_and_wait(
        COMMAND_ID.GET_DAILY_RANK_INFO,
        DailyRankParam(key=key, sub_key=sub_key, start=start, end=end),
        timeout=15.0,
    )
    return list(rank_list.rank_list)


async def _fetch_rank_item(
    game: Any,
    *,
    key: int,
    sub_key: int,
    index: int,
) -> Any | None:
    items = await _fetch_rank_page(
        game,
        key=key,
        sub_key=sub_key,
        start=index,
        end=index,
    )
    return items[0] if items else None


async def fetch_daily_rank_page(
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    count: int,
) -> list[Any]:
    if count <= 0:
        return []

    return await _fetch_rank_page(
        game,
        key=key,
        sub_key=sub_key,
        start=start,
        end=start + count - 1,
    )


def _datetime_to_sub_key(value: datetime) -> int:
    return int(value.strftime("%Y%m%d"))


def get_current_peak_sub_key() -> int | None:
    if plugin_config.seer_query_peak_subkey is not None:
        return plugin_config.seer_query_peak_subkey

    try:
        from seerapi_models import PeakSeasonORM

        from ironsbot.plugins.db_sync.manager import db_manager
    except Exception:  # noqa: BLE001
        return None

    session_gen = db_manager.get_session("seerapi")
    if session_gen is None:
        return None

    try:
        session = next(session_gen)
        season = session.get(PeakSeasonORM, 1)
        if season is None:
            return None
        return _datetime_to_sub_key(season.start_time)
    except Exception:  # noqa: BLE001
        return None
    finally:
        session_gen.close()


async def _find_rank_by_linear_scan(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    limit: int,
    page_size: int,
    result: RankLookupResult,
) -> RankLookupResult:
    start = 0
    while start < limit:
        end = min(start + page_size - 1, limit - 1)
        items = await _fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=end,
        )

        for offset, item in enumerate(items):
            if item.id == user_id:
                result.rank = start + offset + 1
                result.score = item.score
                return result

        if len(items) < end - start + 1:
            return result

        start = end + 1

    return result


async def _find_rank_by_score(  # noqa: C901, PLR0913
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    target_score: int,
    limit: int,
    page_size: int,
    result: RankLookupResult,
) -> RankLookupResult:
    result.score = target_score

    async def score_at(index: int) -> int | None:
        item = await _fetch_rank_item(game, key=key, sub_key=sub_key, index=index)
        return None if item is None else item.score

    low = 0
    high = limit
    while low < high:
        mid = (low + high) // 2
        score = await score_at(mid)
        if score is None or score <= target_score:
            high = mid
        else:
            low = mid + 1

    first_same_or_lower = low
    if first_same_or_lower >= limit:
        return result

    first_score = await score_at(first_same_or_lower)
    if first_score != target_score:
        return result

    low = first_same_or_lower
    high = limit
    while low < high:
        mid = (low + high) // 2
        score = await score_at(mid)
        if score is None or score < target_score:
            high = mid
        else:
            low = mid + 1

    tie_end = min(low, limit)
    start = first_same_or_lower
    while start < tie_end:
        end = min(start + page_size - 1, tie_end - 1)
        items = await _fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=end,
        )

        for offset, item in enumerate(items):
            if item.id == user_id:
                result.rank = start + offset + 1
                result.score = item.score
                return result

        if len(items) < end - start + 1:
            return result

        start = end + 1

    return result


async def _find_rank(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    title: str,
    score_name: str,
    key: int,
    sub_key: int,
    target_score: int | None = None,
    search_limit: int | None = None,
    minimum_score_search_limit: int = 0,
) -> RankLookupResult:
    configured_limit = max(0, plugin_config.seer_query_rank_limit)
    limit = configured_limit if search_limit is None else max(0, search_limit)
    page_size = max(1, min(plugin_config.seer_query_rank_page_size, 100))
    if target_score is not None and target_score > 0:
        limit = max(limit, minimum_score_search_limit)

    result = RankLookupResult(
        title=title,
        score_name=score_name,
        searched_limit=limit,
        queried=limit > 0,
    )

    if limit <= 0:
        return result

    if target_score is not None and target_score > 0:
        return await _find_rank_by_score(
            game,
            user_id=user_id,
            key=key,
            sub_key=sub_key,
            target_score=target_score,
            limit=limit,
            page_size=page_size,
            result=result,
        )

    return await _find_rank_by_linear_scan(
        game,
        user_id=user_id,
        key=key,
        sub_key=sub_key,
        limit=limit,
        page_size=page_size,
        result=result,
    )


async def _find_pet_kind_rank(
    game: Any,
    *,
    user_id: int,
    pet_kind_count: int,
    search_limit: int,
) -> RankLookupResult:
    real_search_limit = max(0, search_limit)
    raw_search_limit = real_search_limit + PET_KIND_RANK_ANOMALY_COUNT
    result = RankLookupResult(
        title="精灵图鉴",
        score_name="精灵",
        score=pet_kind_count or None,
        searched_limit=real_search_limit,
        queried=real_search_limit > 0,
    )

    if is_pet_kind_rank_anomaly_user(user_id):
        result.rank = 0
        if result.score is None:
            result.score = 0
        return result

    if real_search_limit <= 0:
        return result

    raw_result = await _find_rank_by_linear_scan(
        game,
        user_id=user_id,
        key=PET_KIND_RANK_KEY,
        sub_key=PET_KIND_RANK_SUB_KEY,
        limit=raw_search_limit,
        page_size=max(1, min(plugin_config.seer_query_rank_page_size, 100)),
        result=result,
    )
    raw_result.searched_limit = real_search_limit
    if raw_result.rank is not None:
        raw_result.rank = max(0, raw_result.rank - PET_KIND_RANK_ANOMALY_COUNT)
    return raw_result


async def _fetch_book_breakdown_summary(
    game: Any,
    user_id: int,
    *,
    pet_kind_count: int = 0,
    skin_score: int | None = None,
) -> BookBreakdownSummary:
    limit = min(
        max(0, plugin_config.seer_query_rank_limit),
        BOOK_BREAKDOWN_SCAN_LIMIT,
    )
    pet_kind = await _find_pet_kind_rank(
        game,
        user_id=user_id,
        pet_kind_count=pet_kind_count,
        search_limit=limit,
    )
    skin = await _find_rank(
        game,
        user_id=user_id,
        title="皮肤图鉴",
        score_name="皮肤",
        key=SKIN_RANK_KEY,
        sub_key=SKIN_RANK_SUB_KEY,
        target_score=skin_score,
        search_limit=limit,
    )
    countermark = await _find_rank(
        game,
        user_id=user_id,
        title="刻印图鉴",
        score_name="刻印",
        key=COUNTERMARK_RANK_KEY,
        sub_key=COUNTERMARK_RANK_SUB_KEY,
        search_limit=limit,
    )
    outfit_suit = await _find_rank(
        game,
        user_id=user_id,
        title="套装图鉴",
        score_name="套装",
        key=OUTFIT_RANK_KEY,
        sub_key=OUTFIT_SUIT_RANK_SUB_KEY,
        search_limit=limit,
    )
    outfit_part = await _find_rank(
        game,
        user_id=user_id,
        title="部件图鉴",
        score_name="部件",
        key=OUTFIT_RANK_KEY,
        sub_key=OUTFIT_PART_RANK_SUB_KEY,
        search_limit=limit,
    )
    mount = await _find_rank(
        game,
        user_id=user_id,
        title="座驾图鉴",
        score_name="座驾",
        key=OUTFIT_RANK_KEY,
        sub_key=MOUNT_RANK_SUB_KEY,
        search_limit=limit,
    )
    return BookBreakdownSummary(
        pet_kind_count=pet_kind_count,
        pet_kind=pet_kind,
        skin=skin,
        countermark=countermark,
        outfit_suit=outfit_suit,
        outfit_part=outfit_part,
        mount=mount,
    )


async def fetch_peak_season_rank_summary(
    game: Any,
    user_id: int,
    *,
    standard_score: int | None = None,
    wild_score: int | None = None,
    expert_score: int | None = None,
) -> PeakSeasonRankSummary:
    sub_key = get_current_peak_sub_key()
    if sub_key is None:
        return PeakSeasonRankSummary.empty()

    summary = PeakSeasonRankSummary.empty()
    if standard_score is not None and standard_score > 0:
        summary.standard = await _find_rank(
            game,
            user_id=user_id,
            title="竞技赛季榜",
            score_name="段位分",
            key=STANDARD_PEAK_USER_RANK_KEY,
            sub_key=sub_key,
            target_score=standard_score,
            minimum_score_search_limit=PEAK_USER_SCORE_SEARCH_LIMIT,
        )
    if wild_score is not None and wild_score > 0:
        summary.wild = await _find_rank(
            game,
            user_id=user_id,
            title="狂野赛季榜",
            score_name="段位分",
            key=WILD_PEAK_USER_RANK_KEY,
            sub_key=sub_key,
            target_score=wild_score,
            minimum_score_search_limit=PEAK_USER_SCORE_SEARCH_LIMIT,
        )
    if expert_score is not None and expert_score > 0:
        summary.expert = await _find_rank(
            game,
            user_id=user_id,
            title="专家赛季榜",
            score_name="专家积分",
            key=EXPERT_PEAK_USER_RANK_KEY,
            sub_key=sub_key,
            target_score=expert_score,
            minimum_score_search_limit=PEAK_USER_SCORE_SEARCH_LIMIT,
        )
    return summary


async def fetch_player_rank_summary(  # noqa: PLR0913
    game: Any,
    user_id: int,
    *,
    book_score: int | None = None,
    achieve_score: int | None = None,
    pet_kind_count: int = 0,
    skin_score: int | None = None,
) -> PlayerRankSummary:
    book = await _find_rank(
        game,
        user_id=user_id,
        title="图鉴积分",
        score_name="图鉴积分",
        key=BOOK_RANK_KEY,
        sub_key=BOOK_RANK_SUB_KEY,
        target_score=book_score,
    )
    achieve = await _find_rank(
        game,
        user_id=user_id,
        title="成就点数",
        score_name="成就点数",
        key=ACHIEVE_RANK_KEY,
        sub_key=ACHIEVE_RANK_SUB_KEY,
        target_score=achieve_score,
        minimum_score_search_limit=ACHIEVE_SCORE_SEARCH_LIMIT,
    )
    breakdown = await _fetch_book_breakdown_summary(
        game,
        user_id,
        pet_kind_count=pet_kind_count,
        skin_score=skin_score,
    )
    return PlayerRankSummary(book=book, achieve=achieve, breakdown=breakdown)


def format_rank_lookup(result: RankLookupResult) -> str:
    if not result.queried:
        return f"{result.title}：未查询"

    if result.rank is None:
        suffix = (
            ""
            if result.score is None
            else f"（{result.score_name}：{result.score}）"
        )
        return f"{result.title}：前 {result.searched_limit} 名未上榜{suffix}"

    return f"{result.title}：第 {result.rank} 名（{result.score_name}：{result.score}）"


def format_peak_rank_lookup(result: RankLookupResult, *, inactive_text: str) -> str:
    if not result.queried and result.score is None:
        return inactive_text
    if not result.queried:
        return "未查询"
    if result.rank is None:
        return f"前 {result.searched_limit} 名未上榜"
    return f"第 {result.rank} 名"


def _format_score_rank(result: RankLookupResult | None) -> str:
    if result is None or not result.queried:
        return "未查询"

    if result.score is None:
        return f"前 {result.searched_limit} 名未上榜"

    if result.rank is None:
        return f"{result.score}（前 {result.searched_limit} 名未上榜）"

    return f"{result.score}（第 {result.rank} 名）"


def build_peak_rating_score(rank: int, star: int) -> int | None:
    if rank <= 0 and star <= 0:
        return None
    return rank * 100000 + star


def format_book_breakdown(summary: BookBreakdownSummary) -> str:
    outfit_count = summary.outfit_count
    outfit_text = "未知"
    if outfit_count is not None:
        outfit_text = (
            f"{outfit_count}"
            f"（套装 {_format_score_rank(summary.outfit_suit)}；"
            f"部件 {_format_score_rank(summary.outfit_part)}；未找到合并总榜）"
        )

    unlocked_count = summary.unlocked_count
    unlocked_line = (
        "已解锁图鉴条目：未知"
        if unlocked_count is None
        else f"已解锁图鉴条目：{unlocked_count}"
    )

    return "\n".join(
        (
            "【图鉴条目拆分】",
            f"精灵图鉴：{_format_score_rank(summary.pet_kind)}",
            f"皮肤图鉴：{_format_score_rank(summary.skin)}",
            f"装扮图鉴：{outfit_text}",
            f"座驾图鉴：{_format_score_rank(summary.mount)}",
            f"刻印图鉴：{_format_score_rank(summary.countermark)}",
            unlocked_line,
        )
    )


def format_player_rank_summary(summary: PlayerRankSummary) -> str:
    return "\n".join(
        (
            "【全服排行】",
            format_rank_lookup(summary.book),
            format_rank_lookup(summary.achieve),
            "",
            format_book_breakdown(summary.breakdown),
        )
    )
