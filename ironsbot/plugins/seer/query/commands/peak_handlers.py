# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Iterable
from dataclasses import KW_ONLY, dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, NamedTuple, TypedDict

from nonebot.matcher import Matcher
from nonebot.params import Fullmatch
from nonebot_plugin_saa import Image, MessageFactory
from seerapi_models import (
    PeakExpertPoolORM,
    PeakPoolORM,
    PeakPoolVoteORM,
    PeakSeasonORM,
)
from sqlmodel import select

from ironsbot.integrations.headless_seer.game import (
    PEAK_TYPE_NAME_MAP,
    PeakItemData,
    PeakType,
    SeerGame,
)
from ironsbot.integrations.seer_data.getters import (
    SuitDataGetter,
    TitleDataGetter,
)
from ironsbot.integrations.seer_data.resolvers import (
    Getter,
    from_id_get_name,
)
from ironsbot.integrations.seer_data.sessions import AllSessions
from ironsbot.services.seer.rendering.peak_pet_rank import render_peak_pet_rank
from ironsbot.services.seer.rendering.peak_pool import render_peak_pool
from ironsbot.services.seer.rendering.peak_pool_vote import render_peak_pool_vote
from ironsbot.utils import time

from ..depends import PetDataGetter, SeerAPISession

if TYPE_CHECKING:
    from seerapi_models.pet import PetORM

    from ironsbot.integrations.headless_seer.packets import DailyRankList

LIMIT_POOL_VOTE_COUNT = 2
SEMI_LIMIT_POOL_VOTE_COUNT = 3


class UnknownPeakCommandError(ValueError):
    def __init__(self, command: str) -> None:
        super().__init__(f"无法从命令 {command} 中获取巅峰类型")


async def get_standard_limit_pool(
    session: SeerAPISession, matcher: Matcher
) -> list[PeakPoolORM]:
    statement = select(PeakPoolORM)
    pools = session.exec(statement).all()

    if not pools:
        await matcher.finish("❌找不到竞技池数据。（这是一个bug，请反馈给开发者）")

    return list(pools)


async def get_expert_ban_pool(
    session: SeerAPISession, matcher: Matcher
) -> list[PeakExpertPoolORM]:
    statement = select(PeakExpertPoolORM)
    pools = session.exec(statement).all()

    if not pools:
        await matcher.finish("❌找不到专家禁用池数据。（这是一个bug，请反馈给开发者）")

    return list(pools)


async def handle_peak_pool(
    matcher: Matcher,
    pools: list[PeakPoolORM],
) -> None:
    await matcher.send("正在生成图片...")
    start_time = pools[0].start_time.strftime("%Y-%m-%d")
    end_time = pools[0].end_time.strftime("%Y-%m-%d")
    pic_bytes = await render_peak_pool(pools, f"竞技池 / {start_time} ~ {end_time}")
    msg = MessageFactory()
    msg += Image(pic_bytes)
    await msg.finish(at_sender=False)


async def handle_peak_expert_pool(
    matcher: Matcher,
    pools: list[PeakExpertPoolORM],
) -> None:
    await matcher.send("正在生成图片...")
    start_time = pools[0].start_time.strftime("%Y-%m-%d")
    end_time = pools[0].end_time.strftime("%Y-%m-%d")
    pic_bytes = await render_peak_pool(pools, f"专家禁用池 / {start_time} ~ {end_time}")
    msg = MessageFactory()
    msg += Image(pic_bytes)
    await msg.finish(at_sender=False)


class _VoteRank(TypedDict):
    content: "DailyRankList"
    title: str
    pets: "list[PetORM]"


def sort_peak_pool_vote_by_time(
    pool_list: Iterable[PeakPoolVoteORM],
) -> list[PeakPoolVoteORM]:
    """
    根据当前时间对投票模型排序，距离当前时间近的排在前面。
    支持对象拥有 start_time 属性（datetime 类型）。
    """
    now = time.now(tz=time.TZ_CN)

    def time_distance(obj: PeakPoolVoteORM) -> float:
        return abs((obj.start_time - now).total_seconds())

    return sorted(pool_list, key=time_distance)


async def handle_peak_vote(
    matcher: Matcher,
    session: SeerAPISession,
    game: SeerGame,
) -> None:
    pools: list[_VoteRank] = []
    now = time.now(tz=time.TZ_CN)
    for orm in sort_peak_pool_vote_by_time(session.exec(select(PeakPoolVoteORM)).all()):
        title = f"限{orm.count}池票选"
        if orm.start_time > now:
            title += " / 票选未开始"
        elif orm.end_time < now:
            title += " / 票选已结束"
        else:
            start_time = orm.start_time.strftime("%Y-%m-%d")
            end_time = orm.end_time.strftime("%Y-%m-%d")
            title += f"<br>票选时间：{start_time} ~ {end_time}"

        if orm.count == LIMIT_POOL_VOTE_COUNT:
            pool = await game.get_limit_pool_vote(sub_key=orm.subkey)
        elif orm.count == SEMI_LIMIT_POOL_VOTE_COUNT:
            pool = await game.get_semi_limit_pool_vote(sub_key=orm.subkey)
        else:
            continue

        pools.append(
            {
                "content": pool,
                "title": title,
                "pets": orm.pet,
            }
        )

    if not pools:
        await matcher.finish("❌找不到票选数据。")

    await matcher.send("正在生成图片...")
    pic_bytes = await render_peak_pool_vote(pools)
    msg = MessageFactory()
    msg += Image(pic_bytes)
    await msg.finish(at_sender=False)


def _datetime_to_sub_key(time: datetime) -> int:
    return int(time.strftime("%Y%m%d"))


@dataclass(slots=True)
class _RankItem(PeakItemData):
    _: KW_ONLY
    name: str

    def __str__(self) -> str:
        args = [
            self.name,
            f"出场 {self.count}",
            f"胜场 {self.win}",
            f"胜率 {self.win_rate}%",
        ]
        return " | ".join(args)

    @classmethod
    def from_peak_item_data(cls, name: str, item: PeakItemData) -> "_RankItem":
        return cls(
            name=name,
            id=item.id,
            count=item.count,
            win=item.win,
            ban_count=item.ban_count,
        )


@dataclass(slots=True)
class _Rank:
    items: list[_RankItem]

    def __str__(self) -> str:
        return "\n".join(f"{index}. {item}" for index, item in enumerate(self.items, 1))

    @classmethod
    def from_peak_item_data(
        cls, items: list[PeakItemData], *, getter: Getter, sessions: AllSessions
    ) -> "_Rank":
        return cls(
            items=[
                _RankItem.from_peak_item_data(
                    from_id_get_name(getter, item.id, sessions=sessions), item
                )
                for item in items
            ]
        )


class PeakTypeSelection(NamedTuple):
    name: str
    peak_type: PeakType


def get_peak_type(command: Annotated[str, Fullmatch()]) -> PeakTypeSelection:
    if "专家" in command:
        peak_type = PeakType.EXPERT
    elif "狂野" in command:
        peak_type = PeakType.WILD
    elif "竞技" in command:
        peak_type = PeakType.STANDARD
    else:
        raise UnknownPeakCommandError(command)

    return PeakTypeSelection(name=PEAK_TYPE_NAME_MAP[peak_type], peak_type=peak_type)


async def handle_peak_suit(
    matcher: Matcher,
    seerapi_session: SeerAPISession,
    sessions: AllSessions,
    type_selection: PeakTypeSelection,
    game: SeerGame,
) -> None:
    if not (season := seerapi_session.get(PeakSeasonORM, 1)):
        await matcher.finish("❌找不到赛季数据（这是一个bug，请反馈给开发者）。")

    name, peak_type = type_selection
    rank = await game.get_peak_suit_rank(
        sub_key=_datetime_to_sub_key(season.start_time), peak_type=peak_type
    )

    if not rank:
        await matcher.finish("❌找不到套装榜数据。")

    rank = _Rank.from_peak_item_data(rank, getter=SuitDataGetter, sessions=sessions)
    timestamp = time.now(tz=time.TZ_CN).strftime("%Y-%m-%d %H:%M:%S")
    await matcher.finish(f"{name}套装榜（截至{timestamp}）\n{rank}")


async def handle_title(
    matcher: Matcher,
    seerapi_session: SeerAPISession,
    sessions: AllSessions,
    type_selection: PeakTypeSelection,
    game: SeerGame,
) -> None:
    if not (season := seerapi_session.get(PeakSeasonORM, 1)):
        await matcher.finish("❌找不到赛季数据（这是一个bug，请反馈给开发者）。")

    name, peak_type = type_selection
    rank = await game.get_peak_title_rank(
        sub_key=_datetime_to_sub_key(season.start_time), peak_type=peak_type
    )

    if not rank:
        await matcher.finish("❌找不到称号榜数据。")

    rank = _Rank.from_peak_item_data(rank, getter=TitleDataGetter, sessions=sessions)
    timestamp = time.now(tz=time.TZ_CN).strftime("%Y-%m-%d %H:%M:%S")
    await matcher.finish(f"{name}称号榜（截至{timestamp}）\n{rank}")


async def handle_peak_pet(  # noqa: PLR0913
    matcher: Matcher,
    seerapi_session: SeerAPISession,
    command: Annotated[str, Fullmatch()],
    type_selection: PeakTypeSelection,
    expert_pools: list[PeakExpertPoolORM],
    game: SeerGame,
) -> None:
    if not (season := seerapi_session.get(PeakSeasonORM, 1)):
        await matcher.finish("❌找不到赛季数据（这是一个bug，请反馈给开发者）。")

    name, peak_type = type_selection

    if "月" in command:
        category = "月"
        start_time = expert_pools[0].start_time.strftime("%Y-%m-%d")
        end_time = expert_pools[0].end_time.strftime("%Y-%m-%d")
        sub_key = _datetime_to_sub_key(expert_pools[0].start_time) + 1000000000
    else:
        sub_key = _datetime_to_sub_key(season.start_time)
        category = "总"
        start_time = season.start_time.strftime("%Y-%m-%d")
        end_time = season.end_time.strftime("%Y-%m-%d")

    rank = await game.get_peak_pet_rank(sub_key=sub_key, peak_type=peak_type)
    pick_rank = rank[0][:20]
    if not pick_rank:
        await matcher.finish("❌找不到精灵榜数据。")

    ban_rank = rank[1].rank_list[:20]

    pet_map: dict[int, "PetORM"] = {}
    for item in pick_rank:
        pet = PetDataGetter.get(seerapi_session, item.id)
        if pet is not None:
            pet_map[item.id] = pet
    for item in ban_rank:
        if item.id not in pet_map:
            pet = PetDataGetter.get(seerapi_session, item.id)
            if pet is not None:
                pet_map[item.id] = pet

    await matcher.send("正在生成图片...")
    pic_bytes = await render_peak_pet_rank(
        title=f"{name}精灵{category}榜<br>{start_time} ~ {end_time}",
        pick_items=pick_rank,
        ban_items=ban_rank,
        pet_map=pet_map,
    )
    msg = MessageFactory()
    msg += Image(pic_bytes)
    await msg.finish(at_sender=False)
