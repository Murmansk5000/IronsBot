# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Literal, Protocol, cast

from ironsbot.core import time
from ironsbot.integrations.seer_data.peak_repository import (
    PeakPeriodTimes,
    load_peak_period_times,
    load_peak_pet_snapshots,
    load_peak_pool_snapshots,
    load_peak_vote_snapshots,
)
from ironsbot.services.operations.headless_errors import (
    ClientNotInitializedError,
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.services.seer.images import ImageSourceError
from ironsbot.services.seer.rank_peak import datetime_to_sub_key

if TYPE_CHECKING:
    from datetime import datetime

    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.data import SeerDataAccess, SeerDataReader
    from ironsbot.services.seer.rank_models import RankEntry


@dataclass(slots=True)
class PeakItemData:
    id: int
    count: int
    win: int
    ban_count: int | None = None

    @property
    def win_rate(self) -> float:
        if self.count == 0:
            return 0
        return round(self.win / self.count * 100, 2)


class PeakType(Enum):
    STANDARD = 1
    WILD = 2
    EXPERT = 3


@dataclass(frozen=True, slots=True)
class PeakPetPeriod:
    category: str
    start_time: datetime
    end_time: datetime
    sub_key: int


@dataclass(frozen=True, slots=True)
class PeakPetSnapshot:
    """The pet fields peak renderers need after the database session closes."""

    id: int
    name: str
    resource_id: int
    type_id: int


@dataclass(frozen=True, slots=True)
class PeakPoolSnapshot:
    id: int
    count: int
    start_time: datetime
    end_time: datetime
    pets: tuple[PeakPetSnapshot, ...]


@dataclass(frozen=True, slots=True)
class PeakVoteSnapshot:
    id: int
    count: int
    subkey: int
    start_time: datetime
    end_time: datetime
    pets: tuple[PeakPetSnapshot, ...]


def active_peak_pool_limits(
    pools: Iterable[PeakPoolSnapshot],
    *,
    at: datetime | None = None,
) -> dict[int, int]:
    """Return the current standard-pool carry limit for each pet.

    A pet can appear in more than one active pool while the upstream data is
    transitioning.  In that case, retain the stricter limit so the lineup
    marker never advertises a carry count that is too permissive.
    """

    current_time = at or time.now(tz=time.TZ_CN)
    limits: dict[int, int] = {}
    for pool in pools:
        start_time = normalize_peak_vote_time(pool.start_time)
        end_time = normalize_peak_vote_time(pool.end_time)
        if not start_time <= current_time <= end_time:
            continue
        for pet in pool.pets:
            previous_limit = limits.get(pet.id)
            if previous_limit is None or pool.count < previous_limit:
                limits[pet.id] = pool.count
    return limits


def peak_pet_period(
    times: PeakPeriodTimes | None,
    *,
    monthly: bool,
) -> PeakPetPeriod | None:
    if times is None:
        return None
    offset = 1000000000 if monthly else 0
    return PeakPetPeriod(
        category="月" if monthly else "总",
        start_time=times.start_time,
        end_time=times.end_time,
        sub_key=datetime_to_sub_key(times.start_time) + offset,
    )


class PeakGame(Protocol):
    async def get_limit_pool_vote(self, sub_key: int) -> list[RankEntry]: ...

    async def get_semi_limit_pool_vote(self, sub_key: int) -> list[RankEntry]: ...

    async def get_peak_suit_rank(
        self,
        sub_key: int,
        peak_type: PeakType,
    ) -> list[PeakItemData]: ...

    async def get_peak_title_rank(
        self,
        sub_key: int,
        peak_type: PeakType,
    ) -> list[PeakItemData]: ...

    async def get_peak_pet_rank(
        self,
        sub_key: int,
        peak_type: PeakType,
    ) -> tuple[list[PeakItemData], list[RankEntry]]: ...


PEAK_TYPE_NAME_MAP = {
    PeakType.STANDARD: "竞技",
    PeakType.WILD: "狂野",
    PeakType.EXPERT: "专家",
}

PEAK_POOL_COMMANDS = ("竞技池", "巅峰竞技池", "竞技精灵池", "限制池")
PEAK_EXPERT_POOL_COMMANDS = ("专家池", "巅峰专家池", "专家禁用池")
PEAK_VOTE_COMMANDS = (
    "巅峰投票", "巅峰票选", "巅峰池票选", "竞技池票选", "限制池票选"
)
PEAK_SUIT_RANK_COMMANDS = tuple(f"{name}套装榜" for name in PEAK_TYPE_NAME_MAP.values())
PEAK_TITLE_RANK_COMMANDS = tuple(
    f"{name}称号榜" for name in PEAK_TYPE_NAME_MAP.values()
)
PEAK_PET_RANK_COMMANDS = tuple(
    f"{name}精灵{period}榜"
    for period in ("月", "总")
    for name in PEAK_TYPE_NAME_MAP.values()
)
PEAK_QUERY_COMMANDS = (
    *PEAK_POOL_COMMANDS, *PEAK_EXPERT_POOL_COMMANDS, *PEAK_VOTE_COMMANDS
)
PEAK_RANK_COMMANDS = (
    *PEAK_SUIT_RANK_COMMANDS, *PEAK_TITLE_RANK_COMMANDS, *PEAK_PET_RANK_COMMANDS
)

PEAK_PET_KEY_MAP = {
    PeakType.STANDARD: (177, 93, 94),
    PeakType.WILD: (185, 184, 183),
    PeakType.EXPERT: (202, 201, 200),
}

PEAK_SUIT_KEY_MAP = {
    PeakType.STANDARD: (173, 174),
    PeakType.WILD: (186, 187),
    PeakType.EXPERT: (203, 204),
}

PEAK_TITLE_KEY_MAP = {
    PeakType.STANDARD: (175, 176),
    PeakType.WILD: (188, 189),
    PeakType.EXPERT: (205, 206),
}

LIMIT_POOL_VOTE_COUNT = 2
SEMI_LIMIT_POOL_VOTE_COUNT = 3
ProgressReporter = Callable[[str], Awaitable[None]]
PeakPoolRenderer = Callable[
    [tuple[PeakPoolSnapshot, ...], str],
    Awaitable[bytes],
]


@dataclass(frozen=True, slots=True)
class PeakVoteItemSnapshot:
    id: int
    name: str
    score: int


@dataclass(frozen=True, slots=True)
class PeakVotePoolInput:
    title: str
    items: tuple[PeakVoteItemSnapshot, ...]
    pets: tuple[PeakPetSnapshot, ...]


PeakVoteRenderer = Callable[
    [tuple[PeakVotePoolInput, ...], str],
    Awaitable[bytes],
]

@dataclass(frozen=True, slots=True)
class PeakPetPickSnapshot:
    id: int
    count: int
    win: int

    @property
    def win_rate(self) -> float:
        if self.count == 0:
            return 0
        return round(self.win / self.count * 100, 2)


@dataclass(frozen=True, slots=True)
class PeakPetBanSnapshot:
    id: int
    name: str
    score: int


@dataclass(frozen=True, slots=True)
class PeakPetRankRenderInput:
    title: str
    observed_at: str
    pick_items: tuple[PeakPetPickSnapshot, ...]
    ban_items: tuple[PeakPetBanSnapshot, ...]
    pets: tuple[PeakPetSnapshot, ...]


PeakPetRenderer = Callable[[PeakPetRankRenderInput], Awaitable[bytes]]


@dataclass(frozen=True, slots=True)
class PeakRenderSession:
    data: SeerDataReader
    pool: PeakPoolRenderer
    vote: PeakVoteRenderer
    pet: PeakPetRenderer


PeakRenderSessionFactory = Callable[[], AbstractContextManager[PeakRenderSession]]


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PeakQueryResult:
    text: str = ""
    image: bytes | None = None
    message: str = ""


async def _render_peak_result(image: Awaitable[bytes], title: str) -> PeakQueryResult:
    """Report expected render failures; deadlines belong to the shared ports."""
    try:
        return PeakQueryResult(image=await image)
    except ImageSourceError:
        logger.exception("peak image assets unavailable: title=%s", title)
        return PeakQueryResult(message=f"❌{title}图片素材获取失败，请稍后再试。")
    except (TimeoutError, asyncio.TimeoutError):
        logger.warning("peak image render timed out: title=%s", title, exc_info=True)
        return PeakQueryResult(message=f"❌{title}图片生成超时，请稍后再试。")


def normalize_peak_vote_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=time.TZ_CN)
    return value.astimezone(time.TZ_CN)


def sort_peak_pool_votes_by_time(
    pools: Iterable[PeakVoteSnapshot],
) -> list[PeakVoteSnapshot]:
    now = time.now(tz=time.TZ_CN)
    return sorted(
        pools,
        key=lambda item: abs(
            (normalize_peak_vote_time(item.start_time) - now).total_seconds()
        ),
    )


def parse_peak_type(command: str) -> tuple[str, PeakType]:
    if "专家" in command:
        peak_type = PeakType.EXPERT
    elif "狂野" in command:
        peak_type = PeakType.WILD
    elif "竞技" in command:
        peak_type = PeakType.STANDARD
    else:
        msg = f"无法从命令 {command} 中获取巅峰类型"
        raise ValueError(msg)
    return PEAK_TYPE_NAME_MAP[peak_type], peak_type


class PeakQueryService:
    def __init__(
        self,
        data: SeerDataAccess,
        headless: HeadlessService,
        render_session: PeakRenderSessionFactory,
    ) -> None:
        self._data = data
        self._headless = headless
        self._render_session = render_session

    async def pool(
        self,
        *,
        expert: bool,
        progress: ProgressReporter,
    ) -> PeakQueryResult:
        with self._render_session() as rendering:
            with rendering.data.query(
                lambda session: load_peak_pool_snapshots(session, expert=expert)
            ) as loaded_pools:
                pools = tuple(loaded_pools)
            label = "专家禁用池" if expert else "竞技池"
            if not pools:
                return PeakQueryResult(
                    message=(
                        f"❌找不到{label}数据。"
                        "（这是一个bug，请反馈给开发者）"
                    )
                )
            await progress("正在生成图片...")
            start_time = pools[0].start_time.strftime("%Y-%m-%d")
            end_time = pools[0].end_time.strftime("%Y-%m-%d")
            return await _render_peak_result(
                rendering.pool(pools, f"{label} / {start_time} ~ {end_time}"),
                label,
            )

    async def vote(
        self,
        progress: ProgressReporter,
    ) -> PeakQueryResult:
        game, error = self._game()
        if game is None:
            return PeakQueryResult(message=error)
        with self._render_session() as rendering:
            with rendering.data.query(load_peak_vote_snapshots) as loaded_votes:
                votes = tuple(loaded_votes)
            pools: list[PeakVotePoolInput] = []
            now = time.now(tz=time.TZ_CN)
            for vote in sort_peak_pool_votes_by_time(votes):
                start_time = normalize_peak_vote_time(vote.start_time)
                end_time = normalize_peak_vote_time(vote.end_time)
                if not start_time <= now <= end_time:
                    continue
                title = (
                    f"限{vote.count}池票选"
                    f"<br>票选时间：{start_time:%Y-%m-%d} ~ "
                    f"{end_time:%Y-%m-%d}"
                )
                if vote.count == LIMIT_POOL_VOTE_COUNT:
                    rank = await game.get_limit_pool_vote(vote.subkey)
                elif vote.count == SEMI_LIMIT_POOL_VOTE_COUNT:
                    rank = await game.get_semi_limit_pool_vote(vote.subkey)
                else:
                    continue
                pools.append(
                    PeakVotePoolInput(
                        items=tuple(
                            PeakVoteItemSnapshot(
                                id=item.id,
                                name=item.nick,
                                score=item.score,
                            )
                            for item in rank
                        ),
                        title=title,
                        pets=vote.pets,
                    )
                )
            if not pools:
                return PeakQueryResult(message="❌当前没有进行中的巅峰投票。")
            await progress("正在生成图片...")
            return await _render_peak_result(
                rendering.vote(
                    tuple(pools),
                    time.now(tz=time.TZ_CN).strftime("%Y-%m-%d %H:%M"),
                ),
                "巅峰投票",
            )

    async def item_rank(
        self,
        command: str,
        *,
        kind: Literal["套装", "称号"],
    ) -> PeakQueryResult:
        game, error = self._game()
        if game is None:
            return PeakQueryResult(message=error)
        name, peak_type = parse_peak_type(command)
        with self._data.query(
            lambda session: load_peak_period_times(session, monthly=False)
        ) as times:
            period = peak_pet_period(times, monthly=False)
        if period is None:
            return PeakQueryResult(
                message="❌找不到赛季数据（这是一个bug，请反馈给开发者）。"
            )
        if kind == "套装":
            rank_data = await game.get_peak_suit_rank(
                period.sub_key,
                peak_type,
            )
            getter = self._data.suit
        else:
            rank_data = await game.get_peak_title_rank(
                period.sub_key,
                peak_type,
            )
            getter = self._data.title
        if not rank_data:
            return PeakQueryResult(message=f"❌找不到{kind}榜数据。")
        with self._data.get_many(
            getter,
            {item.id for item in rank_data},
        ) as models:
            lines: list[str] = []
            for index, item in enumerate(rank_data, 1):
                model = models.get(item.id)
                item_name = "" if model is None else model.name
                lines.append(
                    f"{index}. {item_name}"
                    f" | 出场 {item.count}"
                    f" | 胜场 {item.win}"
                    f" | 胜率 {item.win_rate}%"
                )
        timestamp = time.now(tz=time.TZ_CN).strftime("%Y-%m-%d %H:%M:%S")
        return PeakQueryResult(
            text=f"{name}{kind}榜（截至{timestamp}）\n" + "\n".join(lines)
        )

    async def pet_rank(
        self,
        command: str,
        progress: ProgressReporter,
    ) -> PeakQueryResult:
        game, error = self._game()
        if game is None:
            return PeakQueryResult(message=error)
        name, peak_type = parse_peak_type(command)
        monthly = "月" in command
        with self._render_session() as rendering:
            with rendering.data.query(
                lambda session: load_peak_period_times(session, monthly=monthly)
            ) as times:
                period = peak_pet_period(times, monthly=monthly)
            if period is None:
                return PeakQueryResult(
                    message=(
                        "❌找不到专家禁用池数据。"
                        "（这是一个bug，请反馈给开发者）"
                        if monthly
                        else "❌找不到赛季数据（这是一个bug，请反馈给开发者）。"
                    )
                )
            pick_rank, ban_rank = await game.get_peak_pet_rank(
                period.sub_key,
                peak_type,
            )
            observed_at = time.now(tz=time.TZ_CN).strftime("%Y-%m-%d %H:%M:%S")
            pick_rank = pick_rank[:20]
            ban_rank = ban_rank[:20]
            if not pick_rank:
                return PeakQueryResult(message="❌找不到精灵榜数据。")
            with rendering.data.query(
                lambda session: load_peak_pet_snapshots(
                    session, {item.id for item in (*pick_rank, *ban_rank)}
                )
            ) as pet_map:
                pets = tuple(sorted(pet_map.values(), key=lambda pet: pet.id))
            await progress("正在生成图片...")
            render_input = PeakPetRankRenderInput(
                observed_at=observed_at,
                title=(
                    f"{name}精灵{period.category}榜<br>"
                    f"{period.start_time:%Y-%m-%d} ~ "
                    f"{period.end_time:%Y-%m-%d}"
                ),
                pick_items=tuple(
                    PeakPetPickSnapshot(
                        id=item.id,
                        count=item.count,
                        win=item.win,
                    )
                    for item in pick_rank
                ),
                ban_items=tuple(
                    PeakPetBanSnapshot(
                        id=item.id,
                        name=item.nick,
                        score=item.score,
                    )
                    for item in ban_rank
                ),
                pets=pets,
            )
            return await _render_peak_result(rendering.pet(render_input), command)

    def _game(self) -> tuple[PeakGame | None, str]:
        try:
            return cast("PeakGame", self._headless.get_game()), ""
        except ClientNotInitializedError:
            return None, "❌ 无头客户端尚未初始化，无法使用此命令"
        except NotLoggedInError:
            return None, "❌ 无头客户端尚未登录，无法使用此命令"
        except DisconnectedError:
            return None, "❌ 无头客户端连接已断开，正在尝试重连，请稍后再试"
