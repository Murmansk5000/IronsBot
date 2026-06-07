# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Iterable
from dataclasses import KW_ONLY, dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, NamedTuple, TypedDict

from nonebot.matcher import Matcher
from nonebot.params import Depends, Fullmatch
from nonebot_plugin_saa import Image, MessageFactory
from seerapi_models import (
    PeakExpertPoolORM,
    PeakPoolORM,
    PeakPoolVoteORM,
    PeakSeasonORM,
)
from sqlmodel import select

from ironsbot.plugins.headless_seer.game import (
    PEAK_TYPE_NAME_MAP,
    PeakItemData,
    PeakType,
    SeerGame,
)
from ironsbot.plugins.seer_data.db import (
    AllSessions,
    Getter,
    SuitDataGetter,
    TitleDataGetter,
    from_id_get_name,
)
from ironsbot.utils import time
from ironsbot.utils.rule import no_reply

from ..depends import GameClient, PetDataGetter, SeerAPISession
from ..group import matcher_group
from ..render import render_peak_pet_rank, render_peak_pool, render_peak_pool_vote

if TYPE_CHECKING:
    from seerapi_models.pet import PetORM

    from ironsbot.plugins.headless_seer.packets import DailyRankList

peak_pool_matcher = matcher_group.on_fullmatch(
    ("竞技池", "巅峰竞技池", "竞技精灵池", "限制池"), rule=no_reply()
)


async def _get_standard_limit_pool(
    session: SeerAPISession, matcher: Matcher
) -> list[PeakPoolORM]:
    statement = select(PeakPoolORM)
    pools = session.exec(statement).all()

    if not pools:
        await matcher.finish("❌找不到竞技池数据。（这是一个bug，请反馈给开发者）")

    return list(pools)


async def _get_expert_ban_pool(
    session: SeerAPISession, matcher: Matcher
) -> list[PeakExpertPoolORM]:
    statement = select(PeakExpertPoolORM)
    pools = session.exec(statement).all()

    if not pools:
        await matcher.finish("❌找不到专家禁用池数据。（这是一个bug，请反馈给开发者）")

    return list(pools)


@peak_pool_matcher.handle()
async def handle_peak_pool(
    matcher: Matcher,
    pools: list[PeakPoolORM] = Depends(_get_standard_limit_pool),
) -> None:
    await matcher.send("正在生成图片...")
    start_time = pools[0].start_time.strftime("%Y-%m-%d")
    end_time = pools[0].end_time.strftime("%Y-%m-%d")
    pic_bytes = await render_peak_pool(pools, f"竞技池 / {start_time} ~ {end_time}")
    msg = MessageFactory()
    msg += Image(pic_bytes)
    await msg.finish(at_sender=False)


peak_expert_pool_matcher = matcher_group.on_fullmatch(
    ("专家池", "巅峰专家池", "专家禁用池"), rule=no_reply()
)


@peak_expert_pool_matcher.handle()
async def handle_peak_expert_pool(
    matcher: Matcher,
    pools: list[PeakExpertPoolORM] = Depends(_get_expert_ban_pool),
) -> None:
    await matcher.send("正在生成图片...")
    start_time = pools[0].start_time.strftime("%Y-%m-%d")
    end_time = pools[0].end_time.strftime("%Y-%m-%d")
    pic_bytes = await render_peak_pool(pools, f"专家禁用池 / {start_time} ~ {end_time}")
    msg = MessageFactory()
    msg += Image(pic_bytes)
    await msg.finish(at_sender=False)


peak_vote_matcher = matcher_group.on_fullmatch(
    ("巅峰投票", "巅峰票选", "巅峰池票选", "竞技池票选", "限制池票选"), rule=no_reply()
)


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


@peak_vote_matcher.handle()
async def handle_peak_vote(
    matcher: Matcher,
    session: SeerAPISession,
    game: SeerGame = GameClient,
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
            title += f"<br>票选时间：{orm.start_time.strftime('%Y-%m-%d')} ~ {orm.end_time.strftime('%Y-%m-%d')}"

        if orm.count == 2:
            pool = await game.get_limit_pool_vote(sub_key=orm.subkey)
        elif orm.count == 3:
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


class _PeakTypeTuple(NamedTuple):
    name: str
    peak_type: PeakType


def _get_peak_type(command: Annotated[str, Fullmatch()]) -> _PeakTypeTuple:
    if "专家" in command:
        peak_type = PeakType.EXPERT
    elif "狂野" in command:
        peak_type = PeakType.WILD
    elif "竞技" in command:
        peak_type = PeakType.STANDARD
    else:
        raise ValueError(f"无法从命令 {command} 中获取巅峰类型")

    return _PeakTypeTuple(name=PEAK_TYPE_NAME_MAP[peak_type], peak_type=peak_type)


peak_suit_matcher = matcher_group.on_fullmatch(
    ("竞技套装榜", "狂野套装榜", "专家套装榜"), rule=no_reply()
)


@peak_suit_matcher.handle()
async def handle_peak_suit(
    matcher: Matcher,
    seerapi_session: SeerAPISession,
    sessions: AllSessions,
    type_tuple: _PeakTypeTuple = Depends(_get_peak_type),
    game: SeerGame = GameClient,
) -> None:
    if not (season := seerapi_session.get(PeakSeasonORM, 1)):
        await matcher.finish("❌找不到赛季数据（这是一个bug，请反馈给开发者）。")

    name, peak_type = type_tuple
    rank = await game.get_peak_suit_rank(
        sub_key=_datetime_to_sub_key(season.start_time), peak_type=peak_type
    )

    if not rank:
        await matcher.finish("❌找不到套装榜数据。")

    rank = _Rank.from_peak_item_data(rank, getter=SuitDataGetter, sessions=sessions)
    await matcher.finish(
        f"{name}套装榜（截至{time.now(tz=time.TZ_CN).strftime('%Y-%m-%d %H:%M:%S')}）\n{rank}"
    )


PEAK_RATING_NAMES = ("学徒", "猛将", "天骄", "王者", "圣皇", "宇宙圣皇")


def _format_peak_rating(data: int) -> str:
    first_digit = int(data / (10 ** (len(str(int(data))) - 1)))
    if first_digit >= len(PEAK_RATING_NAMES):
        return "未知"

    score = data - first_digit * 100000
    end_str = "星" if first_digit >= 4 else "分"
    return f"{PEAK_RATING_NAMES[first_digit]}{score}{end_str}"


title_matcher = matcher_group.on_fullmatch(
    ("竞技称号榜", "狂野称号榜", "专家称号榜"), rule=no_reply()
)


@title_matcher.handle()
async def handle_title(
    matcher: Matcher,
    seerapi_session: SeerAPISession,
    sessions: AllSessions,
    type_tuple: _PeakTypeTuple = Depends(_get_peak_type),
    game: SeerGame = GameClient,
) -> None:
    if not (season := seerapi_session.get(PeakSeasonORM, 1)):
        await matcher.finish("❌找不到赛季数据（这是一个bug，请反馈给开发者）。")

    name, peak_type = type_tuple
    rank = await game.get_peak_title_rank(
        sub_key=_datetime_to_sub_key(season.start_time), peak_type=peak_type
    )

    if not rank:
        await matcher.finish("❌找不到称号榜数据。")

    rank = _Rank.from_peak_item_data(rank, getter=TitleDataGetter, sessions=sessions)
    await matcher.finish(
        f"{name}称号榜（截至{time.now(tz=time.TZ_CN).strftime('%Y-%m-%d %H:%M:%S')}）\n{rank}"
    )


peak_pet_matcher = matcher_group.on_fullmatch(
    (
        "竞技精灵月榜",
        "狂野精灵月榜",
        "专家精灵月榜",
        "竞技精灵总榜",
        "狂野精灵总榜",
        "专家精灵总榜",
    ),
    rule=no_reply(),
)


@peak_pet_matcher.handle()
async def handle_peak_pet(
    matcher: Matcher,
    seerapi_session: SeerAPISession,
    command: Annotated[str, Fullmatch()],
    type_tuple: _PeakTypeTuple = Depends(_get_peak_type),
    expert_pools: list[PeakExpertPoolORM] = Depends(_get_expert_ban_pool),
    game: SeerGame = GameClient,
) -> None:
    if not (season := seerapi_session.get(PeakSeasonORM, 1)):
        await matcher.finish("❌找不到赛季数据（这是一个bug，请反馈给开发者）。")

    name, peak_type = type_tuple

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


peak_user_matcher = matcher_group.on_fullmatch(
    ("竞技段位榜", "狂野段位榜", "专家段位榜"), rule=no_reply()
)


@peak_user_matcher.handle()
async def handle_peak_user(
    matcher: Matcher,
    seerapi_session: SeerAPISession,
    type_tuple: _PeakTypeTuple = Depends(_get_peak_type),
    game: SeerGame = GameClient,
) -> None:
    if not (season := seerapi_session.get(PeakSeasonORM, 1)):
        await matcher.finish("❌找不到赛季数据（这是一个bug，请反馈给开发者）。")

    name, peak_type = type_tuple
    rank = await game.get_peak_user_rank(
        sub_key=_datetime_to_sub_key(season.start_time), peak_type=peak_type
    )
    if not rank:
        await matcher.finish("❌找不到段位榜数据。")

    rating_func = lambda x: f"{x}分"
    if peak_type != PeakType.EXPERT:
        rating_func = _format_peak_rating

    rank_str = "\n".join(
        f"{index}. {item.nick}（{item.id}） {rating_func(item.score)}"
        for index, item in enumerate(rank, 1)
    )
    await matcher.finish(
        f"{name}段位榜（截至{time.now(tz=time.TZ_CN).strftime('%Y-%m-%d %H:%M:%S')}）\n{rank_str}"
    )
