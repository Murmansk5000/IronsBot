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
from ironsbot.core.outbound import BinaryImagePart, OutboundMessage
from ironsbot.services.operations.headless_errors import (
    ClientNotInitializedError,
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.images import ImageSourceError
from ironsbot.services.seer.new_content import NewContentIndexUnavailableError
from ironsbot.services.seer.rank_peak import datetime_to_sub_key

if TYPE_CHECKING:
    from datetime import datetime

    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.new_content import (
        NewContentCategory,
        NewContentSnapshot,
    )
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


PeakPoolChangeState = Literal["changed", "unchanged", "unavailable"]


@dataclass(frozen=True, slots=True)
class PeakPoolTransitionSnapshot:
    pet: PeakPetSnapshot
    previous_limit: int | None
    current_limit: int | None


@dataclass(frozen=True, slots=True)
class PeakPoolRenderSnapshot:
    pools: tuple[PeakPoolSnapshot, ...]
    transitions: tuple[PeakPoolTransitionSnapshot, ...]
    change_state: PeakPoolChangeState
    content_version: str
    expert: bool
    master: bool = False


@dataclass(frozen=True, slots=True)
class PeakVoteSnapshot:
    id: int
    count: int
    subkey: int
    start_time: datetime
    end_time: datetime
    pets: tuple[PeakPetSnapshot, ...]


@dataclass(frozen=True, slots=True)
class PeakPeriodTimes:
    start_time: datetime
    end_time: datetime


class PeakRepository(Protocol):
    def pools(self, *, expert: bool) -> tuple[PeakPoolSnapshot, ...]: ...

    def master_pools(self) -> tuple[PeakPoolSnapshot, ...]: ...

    def votes(self) -> tuple[PeakVoteSnapshot, ...]: ...

    def period(self, *, monthly: bool) -> PeakPeriodTimes | None: ...

    def pets(self, pet_ids: set[int]) -> dict[int, PeakPetSnapshot]: ...

    def item_names(
        self,
        kind: Literal["suit", "title"],
        item_ids: set[int],
    ) -> dict[int, str]: ...


class PeakNewContentSource(Protocol):
    def snapshot(self) -> NewContentSnapshot: ...


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


def _current_peak_pool_limits(
    pools: Iterable[PeakPoolSnapshot],
    *,
    expert: bool,
) -> dict[int, int]:
    limits: dict[int, int] = {}
    for pool in pools:
        limit = 0 if expert else pool.count
        for pet in pool.pets:
            previous = limits.get(pet.id)
            if previous is None or limit < previous:
                limits[pet.id] = limit
    return limits


def _new_content_pool_limit(value: object, *, expert: bool) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return None
    return 0 if expert else limit


def _pool_limit_sort_key(
    value: int | None,
    *,
    expert: bool,
    master: bool,
) -> tuple[int, int]:
    if master:
        return (value is None, -(value or 0))
    order = (0, None) if expert else (0, 2, 3, None)
    try:
        return (0, order.index(value))
    except ValueError:
        return (1, value or 0)


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

PEAK_POOL_COMMANDS = (
    "竞技池",
    "竞技池变化",
    "巅峰竞技池",
    "竞技精灵池",
    "限制池",
)
PEAK_EXPERT_POOL_COMMANDS = (
    "专家池",
    "专家池变化",
    "巅峰专家池",
    "专家禁用池",
)
PEAK_MASTER_POOL_COMMANDS = (
    "大师池",
    "大师池变化",
    "巅峰大师池",
    "大师精灵池",
    "新增大师池",
    "每周大师池",
    "本周大师池",
    "更新大师池",
)
PEAK_VOTE_COMMANDS = ("巅峰投票", "巅峰票选", "巅峰池票选", "竞技池票选", "限制池票选")
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
    *PEAK_POOL_COMMANDS,
    *PEAK_EXPERT_POOL_COMMANDS,
    *PEAK_MASTER_POOL_COMMANDS,
    *PEAK_VOTE_COMMANDS,
)
PEAK_RANK_COMMANDS = (
    *PEAK_SUIT_RANK_COMMANDS,
    *PEAK_TITLE_RANK_COMMANDS,
    *PEAK_PET_RANK_COMMANDS,
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
    [PeakPoolRenderSnapshot, str],
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
    period: str
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
    repository: PeakRepository
    pool: PeakPoolRenderer
    vote: PeakVoteRenderer
    pet: PeakPetRenderer
    new_content: PeakNewContentSource


PeakRenderSessionFactory = Callable[[], AbstractContextManager[PeakRenderSession]]


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PeakQueryResult:
    text: str = ""
    image: bytes | None = None
    message: str = ""

    def to_outbound(self) -> OutboundMessage:
        if self.message:
            return OutboundMessage.from_text(self.message)
        if self.text:
            return OutboundMessage.from_text(self.text)
        if self.image is not None:
            return OutboundMessage((BinaryImagePart(self.image, "image/png"),))
        msg = "peak query result must contain message, text, or image"
        raise ValueError(msg)


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
        repository: PeakRepository,
        headless: HeadlessService,
        render_session: PeakRenderSessionFactory,
    ) -> None:
        self._repository = repository
        self._headless = headless
        self._render_session = render_session

    async def pool(
        self,
        *,
        expert: bool,
        progress: ProgressReporter,
    ) -> PeakQueryResult:
        with self._render_session() as rendering:
            pools = rendering.repository.pools(expert=expert)
            label = "专家禁用池" if expert else "竞技池"
            if not pools:
                return PeakQueryResult(
                    message=(f"❌找不到{label}数据。（这是一个bug，请反馈给开发者）")
                )
            await progress("正在生成图片...")
            start_time = pools[0].start_time.strftime("%Y-%m-%d")
            end_time = pools[0].end_time.strftime("%Y-%m-%d")
            return await _render_peak_result(
                rendering.pool(
                    self._pool_render_snapshot(
                        rendering,
                        pools,
                        expert=expert,
                    ),
                    f"{label} / 有效期：{start_time} ~ {end_time}",
                ),
                label,
            )

    async def master_pool(self, progress: ProgressReporter) -> PeakQueryResult:
        with self._render_session() as rendering:
            pools = rendering.repository.master_pools()
            if not pools:
                return PeakQueryResult(message="❌找不到大师池数据。")
            await progress("正在生成图片...")
            start_time = pools[0].start_time.strftime("%Y-%m-%d")
            end_time = pools[0].end_time.strftime("%Y-%m-%d %H:%M")
            return await _render_peak_result(
                rendering.pool(
                    self._pool_render_snapshot(
                        rendering,
                        pools,
                        expert=False,
                        master=True,
                    ),
                    f"大师池 / 精灵竞技点 / 有效期：{start_time} ~ {end_time}",
                ),
                "大师池",
            )

    @staticmethod
    def _pool_render_snapshot(
        rendering: PeakRenderSession,
        pools: tuple[PeakPoolSnapshot, ...],
        *,
        expert: bool,
        master: bool = False,
    ) -> PeakPoolRenderSnapshot:
        category: NewContentCategory = (
            "peak_master_pool"
            if master
            else ("peak_expert_pool" if expert else "peak_pool")
        )
        try:
            snapshot = rendering.new_content.snapshot()
        except (DataUnavailableError, NewContentIndexUnavailableError) as error:
            logger.warning(
                "peak pool weekly changes unavailable: category=%s error=%s",
                category,
                type(error).__name__,
            )
            return PeakPoolRenderSnapshot(
                pools,
                (),
                "unavailable",
                "",
                expert,
                master,
            )
        content_version = f"{snapshot.config_version}:{snapshot.weekly_cycle}"
        if not snapshot.is_category_comparable(category):
            logger.info(
                "peak pool weekly changes not comparable: category=%s reason=%s",
                category,
                snapshot.category_state(category).reason,
            )
            return PeakPoolRenderSnapshot(
                pools,
                (),
                "unavailable",
                content_version,
                expert,
                master,
            )

        items = snapshot.items_for(category)
        current_pets = {pet.id: pet for pool in pools for pet in pool.pets}
        changed_pets = rendering.repository.pets(
            {item.entity_id for item in items} - set(current_pets)
        )
        current_limits = _current_peak_pool_limits(pools, expert=expert)
        transitions: list[PeakPoolTransitionSnapshot] = []
        for item in items:
            previous_limit = _new_content_pool_limit(
                item.payload.get("previous_limit"),
                expert=expert,
            )
            declared_current = _new_content_pool_limit(
                item.payload.get("current_limit"),
                expert=expert,
            )
            current_limit = current_limits.get(item.entity_id)
            if declared_current != current_limit:
                logger.warning(
                    "peak pool change target differs from current pool: "
                    "category=%s pet_id=%s declared=%s current=%s",
                    category,
                    item.entity_id,
                    declared_current,
                    current_limit,
                )
            if previous_limit == current_limit:
                continue
            pet = current_pets.get(item.entity_id) or changed_pets.get(item.entity_id)
            if pet is None:
                logger.warning(
                    "peak pool change pet metadata missing: category=%s pet_id=%s",
                    category,
                    item.entity_id,
                )
                pet = PeakPetSnapshot(
                    item.entity_id,
                    item.name,
                    item.entity_id,
                    0,
                )
            transitions.append(
                PeakPoolTransitionSnapshot(pet, previous_limit, current_limit)
            )
        transitions.sort(
            key=lambda item: (
                _pool_limit_sort_key(
                    item.previous_limit,
                    expert=expert,
                    master=master,
                ),
                _pool_limit_sort_key(
                    item.current_limit,
                    expert=expert,
                    master=master,
                ),
                item.pet.id,
            )
        )
        return PeakPoolRenderSnapshot(
            pools,
            tuple(transitions),
            "changed" if transitions else "unchanged",
            content_version,
            expert,
            master,
        )

    async def vote(
        self,
        progress: ProgressReporter,
    ) -> PeakQueryResult:
        game, error = self._game()
        if game is None:
            return PeakQueryResult(message=error)
        with self._render_session() as rendering:
            votes = rendering.repository.votes()
            pools: list[PeakVotePoolInput] = []
            now = time.now(tz=time.TZ_CN)
            for vote in sort_peak_pool_votes_by_time(votes):
                start_time = normalize_peak_vote_time(vote.start_time)
                end_time = normalize_peak_vote_time(vote.end_time)
                if not start_time <= now <= end_time:
                    continue
                if vote.count == LIMIT_POOL_VOTE_COUNT:
                    title = "限制级"
                    rank = await game.get_limit_pool_vote(vote.subkey)
                elif vote.count == SEMI_LIMIT_POOL_VOTE_COUNT:
                    title = "准限制级"
                    rank = await game.get_semi_limit_pool_vote(vote.subkey)
                else:
                    continue
                period = (
                    f"{start_time.month}月{start_time.day}日{start_time.hour}点"
                    f" - {end_time.month}月{end_time.day}日{end_time.hour}点"
                )
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
                        period=period,
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
        period = peak_pet_period(self._repository.period(monthly=False), monthly=False)
        if period is None:
            return PeakQueryResult(
                message="❌找不到赛季数据（这是一个bug，请反馈给开发者）。"
            )
        if kind == "套装":
            rank_data = await game.get_peak_suit_rank(
                period.sub_key,
                peak_type,
            )
            item_kind: Literal["suit", "title"] = "suit"
        else:
            rank_data = await game.get_peak_title_rank(
                period.sub_key,
                peak_type,
            )
            item_kind = "title"
        if not rank_data:
            return PeakQueryResult(message=f"❌找不到{kind}榜数据。")
        names = self._repository.item_names(item_kind, {item.id for item in rank_data})
        lines: list[str] = []
        for index, item in enumerate(rank_data, 1):
            lines.append(
                f"{index}. {names.get(item.id, '')}"
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
            period = peak_pet_period(
                rendering.repository.period(monthly=monthly), monthly=monthly
            )
            if period is None:
                return PeakQueryResult(
                    message=(
                        "❌找不到专家禁用池数据。（这是一个bug，请反馈给开发者）"
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
            pet_map = rendering.repository.pets(
                {item.id for item in (*pick_rank, *ban_rank)}
            )
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
