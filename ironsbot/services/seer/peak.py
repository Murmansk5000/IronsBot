# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict, cast

from seerapi_models import (
    PeakExpertPoolORM,
    PeakPoolORM,
    PeakPoolVoteORM,
    PeakSeasonORM,
)
from sqlmodel import Session, select

from ironsbot.core import time
from ironsbot.services.operations.headless_errors import (
    ClientNotInitializedError,
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.external_references import (
    SeerInfoReference,
    peak_rank_reference,
)
from ironsbot.services.seer.new_content import NewContentIndexUnavailableError
from ironsbot.services.seer.rank_peak import datetime_to_sub_key

if TYPE_CHECKING:
    from datetime import datetime

    from seerapi_models.pet import PetORM

    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.new_content import NewContentService
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


@dataclass(frozen=True, slots=True)
class PeakVoteSnapshot:
    id: int
    count: int
    subkey: int
    start_time: datetime
    end_time: datetime
    pets: tuple[PeakPetSnapshot, ...]


def load_peak_pools(
    session: Session,
    *,
    expert: bool,
) -> tuple[PeakPoolORM | PeakExpertPoolORM, ...]:
    model = PeakExpertPoolORM if expert else PeakPoolORM
    return tuple(session.exec(select(model)).all())


def load_peak_votes(session: Session) -> tuple[PeakPoolVoteORM, ...]:
    return tuple(session.exec(select(PeakPoolVoteORM)).all())


def snapshot_peak_pools(
    pools: Iterable[PeakPoolORM | PeakExpertPoolORM],
) -> tuple[PeakPoolSnapshot, ...]:
    return tuple(
        PeakPoolSnapshot(
            id=int(pool.id),
            count=int(pool.count),
            start_time=pool.start_time,
            end_time=pool.end_time,
            pets=tuple(_snapshot_peak_pet(pet) for pet in pool.pet),
        )
        for pool in pools
    )


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
    if not isinstance(value, (int, str)):
        return None
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return None
    return 0 if expert else limit


def _pool_limit_sort_key(value: int | None, *, expert: bool) -> int:
    order = (0, None) if expert else (0, 2, 3, None)
    try:
        return order.index(value)
    except ValueError:
        return len(order)


def snapshot_peak_votes(
    votes: Iterable[PeakPoolVoteORM],
) -> tuple[PeakVoteSnapshot, ...]:
    return tuple(
        PeakVoteSnapshot(
            id=int(vote.id),
            count=int(vote.count),
            subkey=int(vote.subkey),
            start_time=vote.start_time,
            end_time=vote.end_time,
            pets=tuple(_snapshot_peak_pet(pet) for pet in vote.pet),
        )
        for vote in votes
    )


def snapshot_peak_pet_map(
    pets: dict[int, PetORM],
) -> dict[int, PeakPetSnapshot]:
    return {
        int(pet_id): _snapshot_peak_pet(pet)
        for pet_id, pet in pets.items()
    }


def _snapshot_peak_pet(pet: PetORM) -> PeakPetSnapshot:
    return PeakPetSnapshot(
        id=int(pet.id),
        name=str(pet.name),
        resource_id=int(pet.resource_id),
        type_id=int(pet.type_id),
    )


def load_peak_pet_period(
    session: Session,
    *,
    monthly: bool,
) -> PeakPetPeriod | None:
    if monthly:
        pool = session.exec(select(PeakExpertPoolORM)).first()
        if pool is None:
            return None
        return PeakPetPeriod(
            category="月",
            start_time=pool.start_time,
            end_time=pool.end_time,
            sub_key=datetime_to_sub_key(pool.start_time) + 1000000000,
        )

    season = session.get(PeakSeasonORM, 1)
    if season is None:
        return None
    return PeakPetPeriod(
        category="总",
        start_time=season.start_time,
        end_time=season.end_time,
        sub_key=datetime_to_sub_key(season.start_time),
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
PEAK_VOTE_RENDER_TIMEOUT_SECONDS = 45.0
ProgressReporter = Callable[[str], Awaitable[None]]
PeakPoolRenderer = Callable[
    [PeakPoolRenderSnapshot, str],
    Awaitable[bytes],
]


class PeakVoteRank(TypedDict):
    items: list[RankEntry]
    title: str
    pets: list[PeakPetSnapshot]


PeakVoteRenderer = Callable[[list[PeakVoteRank]], Awaitable[bytes]]

logger = logging.getLogger(__name__)


class PeakPetRenderer(Protocol):
    async def __call__(
        self,
        *,
        title: str,
        pick_items: list[PeakItemData],
        ban_items: list[RankEntry],
        pet_map: dict[int, PeakPetSnapshot],
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class PeakQueryResult:
    text: str = ""
    image: bytes | None = None
    message: str = ""
    reference: SeerInfoReference | None = None


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
    def __init__(  # noqa: PLR0913 - service dependencies are explicit
        self,
        data: SeerDataAccess,
        headless: HeadlessService,
        render_pool: PeakPoolRenderer,
        render_vote: PeakVoteRenderer,
        render_pet: PeakPetRenderer,
        *,
        new_content: NewContentService,
    ) -> None:
        self._data = data
        self._headless = headless
        self._render_pool = render_pool
        self._render_vote = render_vote
        self._render_pet = render_pet
        self._new_content = new_content

    async def pool(
        self,
        *,
        expert: bool,
        progress: ProgressReporter,
    ) -> PeakQueryResult:
        with self._data.query(
            partial(load_peak_pools, expert=expert)
        ) as database_pools:
            pools = snapshot_peak_pools(database_pools)
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
        render_snapshot = self._pool_render_snapshot(pools, expert=expert)
        image = await self._render_pool(
            render_snapshot,
            f"{label} / {start_time} ~ {end_time}",
        )
        return PeakQueryResult(image=image, reference=SeerInfoReference.PEAK_POOL)

    def _pool_render_snapshot(
        self,
        pools: tuple[PeakPoolSnapshot, ...],
        *,
        expert: bool,
    ) -> PeakPoolRenderSnapshot:
        category = "peak_expert_pool" if expert else "peak_pool"
        try:
            snapshot = self._new_content.snapshot()
        except (DataUnavailableError, NewContentIndexUnavailableError) as error:
            logger.warning(
                "peak pool weekly changes unavailable: category=%s error=%s",
                category,
                type(error).__name__,
            )
            return PeakPoolRenderSnapshot(
                pools=pools,
                transitions=(),
                change_state="unavailable",
                content_version="",
                expert=expert,
            )
        if not snapshot.is_category_comparable(category):
            logger.info(
                "peak pool weekly changes not comparable: category=%s reason=%s",
                category,
                snapshot.category_state(category).reason,
            )
            return PeakPoolRenderSnapshot(
                pools=pools,
                transitions=(),
                change_state="unavailable",
                content_version=(
                    f"{snapshot.config_version}:{snapshot.weekly_cycle}"
                ),
                expert=expert,
            )

        items = snapshot.items_for(category)
        current_pets = {
            pet.id: pet
            for pool in pools
            for pet in pool.pets
        }
        missing_ids = {item.entity_id for item in items} - set(current_pets)
        changed_pets: dict[int, PeakPetSnapshot] = {}
        if missing_ids:
            with self._data.get_many(self._data.pet, missing_ids) as loaded:
                changed_pets = snapshot_peak_pet_map(loaded)
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
                    id=item.entity_id,
                    name=item.name,
                    resource_id=item.entity_id,
                    type_id=0,
                )
            transitions.append(
                PeakPoolTransitionSnapshot(
                    pet=pet,
                    previous_limit=previous_limit,
                    current_limit=current_limit,
                )
            )
        transitions.sort(
            key=lambda item: (
                _pool_limit_sort_key(item.previous_limit, expert=expert),
                _pool_limit_sort_key(item.current_limit, expert=expert),
                item.pet.id,
            )
        )
        return PeakPoolRenderSnapshot(
            pools=pools,
            transitions=tuple(transitions),
            change_state="changed" if transitions else "unchanged",
            content_version=f"{snapshot.config_version}:{snapshot.weekly_cycle}",
            expert=expert,
        )

    async def vote(
        self,
        progress: ProgressReporter,
    ) -> PeakQueryResult:
        game, error = self._game()
        if game is None:
            return PeakQueryResult(message=error)
        with self._data.query(load_peak_votes) as database_votes:
            votes = snapshot_peak_votes(database_votes)
        pools: list[PeakVoteRank] = []
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
                {"items": rank, "title": title, "pets": list(vote.pets)}
            )
        if not pools:
            return PeakQueryResult(message="❌当前没有进行中的巅峰投票。")
        await progress("正在生成图片...")
        try:
            image = await asyncio.wait_for(
                self._render_vote(pools),
                timeout=PEAK_VOTE_RENDER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "peak vote render timed out: pools=%s timeout_seconds=%s",
                len(pools),
                PEAK_VOTE_RENDER_TIMEOUT_SECONDS,
            )
            return PeakQueryResult(
                message="❌巅峰投票图片生成超时，请稍后再试。"
            )
        except Exception:
            logger.exception("peak vote render failed: pools=%s", len(pools))
            return PeakQueryResult(message="❌巅峰投票图片生成失败，请稍后再试。")
        return PeakQueryResult(image=image, reference=SeerInfoReference.PEAK_VOTE)

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
            partial(load_peak_pet_period, monthly=False)
        ) as database_period:
            period = database_period
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
            text=f"{name}{kind}榜（截至{timestamp}）\n" + "\n".join(lines),
            reference=peak_rank_reference(
                peak_type=peak_type.value,
                category="suit" if kind == "套装" else "title",
            ),
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
        with self._data.query(
            partial(load_peak_pet_period, monthly=monthly)
        ) as database_period:
            period = database_period
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
        pick_rank = pick_rank[:20]
        ban_rank = ban_rank[:20]
        if not pick_rank:
            return PeakQueryResult(message="❌找不到精灵榜数据。")
        with self._data.get_many(
            self._data.pet,
            {item.id for item in (*pick_rank, *ban_rank)},
        ) as database_pets:
            pet_map = snapshot_peak_pet_map(database_pets)
        await progress("正在生成图片...")
        image = await self._render_pet(
            title=(
                f"{name}精灵{period.category}榜<br>"
                f"{period.start_time:%Y-%m-%d} ~ "
                f"{period.end_time:%Y-%m-%d}"
            ),
            pick_items=pick_rank,
            ban_items=ban_rank,
            pet_map=pet_map,
        )
        return PeakQueryResult(
            image=image,
            reference=peak_rank_reference(
                peak_type=peak_type.value,
                category="pet",
            ),
        )

    def _game(self) -> tuple[PeakGame | None, str]:
        try:
            return cast("PeakGame", self._headless.get_game()), ""
        except ClientNotInitializedError:
            return None, "❌ 无头客户端尚未初始化，无法使用此命令"
        except NotLoggedInError:
            return None, "❌ 无头客户端尚未登录，无法使用此命令"
        except DisconnectedError:
            return None, "❌ 无头客户端连接已断开，正在尝试重连，请稍后再试"
