# SPDX-License-Identifier: MIT

from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.plugin import on_message
from nonebot_plugin_saa import Mention, MessageFactory, Text
from seerapi_models import PetORM
from sqlmodel import func, select

from ironsbot.plugins.seer_data.db import SeerAPISession, SQLModelSession
from ironsbot.plugins.seer_data.image import PetHeadImageGetter
from ironsbot.plugins.seer_data.type_calc import calc_multiplier, load_relation_map
from ironsbot.utils.rule import no_reply, startswith_or_endswith

matcher = on_message(
    rule=startswith_or_endswith("抛精灵") & no_reply(),
    priority=3,
    block=True,
)

_REQUIRED_AT_COUNT = 2


def _extract_at_user_ids(event: Event) -> list[str]:
    """按出现顺序提取消息中 @ 的用户 ID（去重，忽略 @全体成员）。"""
    user_ids: list[str] = []
    for segment in event.get_message():
        if segment.type != "at":
            continue
        # OneBot v11 的 At 段使用 qq 字段，其余适配器多为 user_id 字段
        user_id = segment.data.get("qq") or segment.data.get("user_id")
        if user_id is None:
            continue
        user_id = str(user_id)
        if user_id == "all" or user_id in user_ids:
            continue
        user_ids.append(user_id)
    return user_ids


def _summon_pets(session: SQLModelSession) -> list[PetORM]:
    """随机召唤两只不同的精灵。"""
    pets = session.exec(
        select(PetORM).order_by(func.random()).limit(_REQUIRED_AT_COUNT)
    ).all()
    return list(pets)


def _judge_winner(
    pet_a: PetORM,
    pet_b: PetORM,
    multiplier_ab: float,
    multiplier_ba: float,
) -> int:
    """判定胜者在 (pet_a, pet_b) 中的下标：克制倍率高者胜，相同时序号大者胜。"""
    if multiplier_ab > multiplier_ba:
        return 0
    if multiplier_ba > multiplier_ab:
        return 1
    return 0 if pet_a.id > pet_b.id else 1


def _usage_message(at_count: int) -> str:
    if at_count <= 0:
        return "请@两名用户后再抛精灵，例如：抛精灵 @张三 @李四"
    if at_count == 1:
        return "只@了一名用户，还需要再@一名对手哦"
    return "一次最多只能@两名用户哦"


def _format_multiplier(value: float) -> str:
    return f"{value:g}"


@matcher.handle()
async def handle_pet_flip(
    matcher: Matcher,
    event: Event,
    session: SeerAPISession,
) -> None:
    user_ids = _extract_at_user_ids(event)
    if len(user_ids) != _REQUIRED_AT_COUNT:
        await matcher.finish(_usage_message(len(user_ids)))

    pets = _summon_pets(session)
    if len(pets) != _REQUIRED_AT_COUNT:
        await matcher.finish("❌精灵数据库暂无数据，请检查数据源后再试")

    pet_a, pet_b = pets
    table = load_relation_map(session)
    multiplier_ab = calc_multiplier(table, pet_a.type, pet_b.type)
    multiplier_ba = calc_multiplier(table, pet_b.type, pet_a.type)

    winner_index = _judge_winner(pet_a, pet_b, multiplier_ab, multiplier_ba)
    winner_user = user_ids[winner_index]

    msg = MessageFactory([Text("🎲抛精灵！\n")])
    for user_id, pet in zip(user_ids, pets, strict=True):
        msg += Mention(user_id)
        msg += f" 召唤了【{pet.name}】（{pet.type.name} · ID: {pet.id}）\n"
        msg += await PetHeadImageGetter.get(str(pet.resource_id))

    tie = multiplier_ab == multiplier_ba
    prefix = "⚖️克制系数" if tie else "⚔️克制系数"
    tie_suffix = "，序号大者胜 —— " if tie else " —— "
    msg += (
        f"{prefix} {_format_multiplier(multiplier_ab)}"
        f" : {_format_multiplier(multiplier_ba)}{tie_suffix}"
    )
    msg += Mention(winner_user)
    msg += " 获胜！"
    await msg.finish()
