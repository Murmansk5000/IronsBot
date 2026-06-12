# SPDX-License-Identifier: GPL-3.0-or-later
"""Custom high-priority entry points for upstream Seer info queries.

These matchers keep upstream query behavior available through the custom plugin
without editing the upstream plugin code. They intentionally reuse upstream
handlers and renderers, while registering at the custom plugin priority so they
win before the original matchers.
"""

from typing import Annotated

from httpx import HTTPStatusError, RequestError
from nonebot.adapters import Event
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import Depends, Fullmatch
from nonebot.typing import T_State
from nonebot_plugin_saa import Image, MessageFactory, Text
from seerapi_models import PetORM, PetSkinORM
from sqlmodel import select

from ironsbot.plugins.http_client import get_http_origin_client
from ironsbot.plugins.seer_data.db import SQLModelSession
from ironsbot.plugins.seer_data.image import PreviewImageGetter
from ironsbot.services.seer.rendering.custom_pet_info import render_custom_pet_info
from ironsbot.services.seer.skin_price import format_skin_price_lines
from ironsbot.services.seer.weekly_preview import load_weekly_preview_links
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from .._upstream.commands import peak as upstream_peak
from .._upstream.commands import pet as upstream_pet
from ..depends import (
    GetPetData,
    PetDataGetter,
    SeerAPISession,
)
from ..group import matcher_group
from ..prompt import (
    Prompt,
    PromptItem,
    enter_prompt,
    simple_prompt_resolver,
)
from ..upstream_commands import cloth as upstream_cloth
from ..upstream_commands import effect as upstream_effect
from ..upstream_commands import mintmark as upstream_mintmark
from ..upstream_commands import other as upstream_other
from ..upstream_commands import type as upstream_type

UPSTREAM_QUERY_PLUGIN_NAME = "seer_upstream_queries"
UPSTREAM_QUERY_ACTION_METHODS = {
    "pet_image": "_handle_pet_image",
    "pet_info": "_handle_pet_info",
    "preview": "_handle_preview",
    "data_version": "_handle_data_version",
    "mintmark": "_handle_mintmark",
    "gem": "_handle_gem",
    "type": "_handle_type",
    "battle_effect": "_handle_battle_effect",
    "suit": "_handle_suit",
    "equip": "_handle_equip",
    "title": "_handle_title",
    "peak_pool": "_handle_peak_pool",
    "peak_expert_pool": "_handle_peak_expert_pool",
    "peak_vote": "_handle_peak_vote",
    "peak_suit": "_handle_peak_suit",
    "peak_title": "_handle_peak_title",
    "peak_pet": "_handle_peak_pet",
    "peak_user": "_handle_peak_user",
}

pet_image_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        prefixes=("立绘", "皮肤", "查询立绘"),
    )
    & no_reply()
)


class UpstreamQueryPlugin:
    name = UPSTREAM_QUERY_PLUGIN_NAME
    feature = "seer"
    enabled = True

    async def handle(self, event: Event, context: PluginContext) -> None:
        matcher = context.matcher
        if matcher is None:
            return

        method_name = UPSTREAM_QUERY_ACTION_METHODS.get(context.action or "")
        if method_name is None:
            return

        await getattr(self, method_name)(matcher, event, context)

    async def _handle_pet_image(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        state = context.state
        if state is None:
            return
        session: SeerAPISession = context.data["session"]
        arg = str(context.data.get("arg", ""))
        items: list[PromptItem[int]] = context.data["items"]

        if not items:
            raise FinishedException

        if len(items) == 1:
            msg = await _build_pet_image_message(items[0], session)
            await msg.finish()

        if len(items) > upstream_pet.PROMPT_MAX_ITEMS:
            if len(arg) == 1:
                for item in items:
                    if item.name == arg:
                        msg = await _build_pet_image_message(item, session)
                        await msg.finish()

            await matcher.finish(
                f"重名超过{upstream_pet.PROMPT_MAX_ITEMS}个，请重新检索关键词！"
            )

        prompt = Prompt(title="请问你想查询的立绘是……", items=items)
        await enter_prompt(matcher, event, state, prompt, _pet_image_resolver)

    async def _handle_pet_info(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        state = context.state
        if state is None:
            return
        arg = str(context.data.get("arg", ""))
        pets: tuple[PetORM, ...] = context.data["pets"]

        if not pets:
            raise FinishedException

        if len(pets) == 1:
            msg = await _build_pet_info_message(pets[0])
            await msg.finish()

        if len(pets) > upstream_pet.PROMPT_MAX_ITEMS:
            if len(arg) == 1:
                for pet in pets:
                    if pet.name == arg:
                        msg = await _build_pet_info_message(pet)
                        await msg.finish()

            await matcher.finish(
                f"重名超过{upstream_pet.PROMPT_MAX_ITEMS}个，请重新检索关键词！"
            )

        prompt = Prompt(
            title="请问你想查询的精灵是……",
            items=[
                PromptItem(name=pet.name, desc=str(pet.id), value=pet.id)
                for pet in pets
            ],
        )
        await enter_prompt(
            matcher,
            event,
            state,
            prompt,
            simple_prompt_resolver(PetDataGetter, _build_pet_info_message, "精灵"),
        )

    async def _handle_preview(
        self,
        _: Matcher,
        __: Event,
        context: PluginContext,
    ) -> None:
        session: SeerAPISession = context.data["session"]
        image_url, source_url = load_weekly_preview_links(session)
        msg = MessageFactory()
        msg += await _fetch_weekly_preview_image(image_url)
        msg += Text(f"\n预告图来自 {source_url}")
        await msg.finish()

    async def _handle_data_version(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await upstream_other.handle_data_version(
            matcher=matcher,
            session=context.data["session"],
        )

    async def _handle_mintmark(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await upstream_mintmark.handle_mintmark(
            matcher=matcher,
            state=context.state if context.state is not None else {},
            event=event,
            mintmarks=context.data["mintmarks"],
            classes=context.data["classes"],
        )

    async def _handle_gem(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await upstream_mintmark.handle_gem(
            matcher=matcher,
            state=context.state if context.state is not None else {},
            event=event,
            categories=context.data["categories"],
        )

    async def _handle_type(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await upstream_type.handle_type(
            matcher=matcher,
            state=context.state if context.state is not None else {},
            event=event,
            session=context.data["session"],
            type_combinations=context.data["type_combinations"],
        )

    async def _handle_battle_effect(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await upstream_effect.handle_battle_effect(
            matcher=matcher,
            event=event,
            state=context.state if context.state is not None else {},
            battle_effects=context.data["battle_effects"],
        )

    async def _handle_suit(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await upstream_cloth.handle_suit(
            matcher=matcher,
            state=context.state if context.state is not None else {},
            event=event,
            suits=context.data["suits"],
        )

    async def _handle_equip(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await upstream_cloth.handle_equip(
            matcher=matcher,
            state=context.state if context.state is not None else {},
            event=event,
            equips=context.data["equips"],
        )

    async def _handle_title(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await upstream_cloth.handle_title(
            matcher=matcher,
            state=context.state if context.state is not None else {},
            event=event,
            titles=context.data["titles"],
        )

    async def _handle_peak_pool(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await upstream_peak.handle_peak_pool(
            matcher=matcher,
            pools=context.data["pools"],
        )

    async def _handle_peak_expert_pool(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await upstream_peak.handle_peak_expert_pool(
            matcher=matcher,
            pools=context.data["pools"],
        )

    async def _handle_peak_vote(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await upstream_peak.handle_peak_vote(
            matcher=matcher,
            session=context.data["session"],
            game=context.data["game"],
        )

    async def _handle_peak_suit(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await upstream_peak.handle_peak_suit(
            matcher=matcher,
            seerapi_session=context.data["seerapi_session"],
            sessions=context.data["sessions"],
            type_tuple=context.data["type_tuple"],
            game=context.data["game"],
        )

    async def _handle_peak_title(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await upstream_peak.handle_title(
            matcher=matcher,
            seerapi_session=context.data["seerapi_session"],
            sessions=context.data["sessions"],
            type_tuple=context.data["type_tuple"],
            game=context.data["game"],
        )

    async def _handle_peak_pet(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await upstream_peak.handle_peak_pet(
            matcher=matcher,
            seerapi_session=context.data["seerapi_session"],
            command=context.data["command"],
            type_tuple=context.data["type_tuple"],
            expert_pools=context.data["expert_pools"],
            game=context.data["game"],
        )

    async def _handle_peak_user(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await upstream_peak.handle_peak_user(
            matcher=matcher,
            seerapi_session=context.data["seerapi_session"],
            type_tuple=context.data["type_tuple"],
            game=context.data["game"],
        )


register_plugin(UpstreamQueryPlugin())


@pet_image_matcher.handle()
async def _handle_pet_image(  # noqa: PLR0913
    matcher: Matcher,
    state: T_State,
    event: Event,
    session: SeerAPISession,
    arg: str = Depends(parse_string_arg),
    items: list[PromptItem[int]] = Depends(upstream_pet._create_prompt_items),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="pet_image",
        session=session,
        arg=arg,
        items=items,
    )

async def _build_pet_image_message(
    item: PromptItem[int],
    session: SQLModelSession,
):
    msg = await upstream_pet.build_pet_image_message(item, session)
    model = session.exec(
        select(PetSkinORM).where(PetSkinORM.resource_id == item.value)
    ).first()
    if model is None:
        return msg

    msg += format_skin_price_lines(
        session,
        model.id,
        existing_card_price=model.card_price,
    )
    return msg


async def _pet_image_resolver(
    item: PromptItem[int],
    _: Matcher,
    session: SQLModelSession,
) -> None:
    msg = await _build_pet_image_message(item, session)
    await msg.send()

pet_info_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        prefixes=("精灵", "查询精灵信息", "魂印", "技能"),
        suffixes=("查询精灵信息", "魂印", "技能"),
    )
    & no_reply()
)


@pet_info_matcher.handle()
async def _handle_pet_info(
    matcher: Matcher,
    state: T_State,
    event: Event,
    arg: str = Depends(parse_string_arg),
    pets: tuple[PetORM, ...] = GetPetData(),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="pet_info",
        arg=arg,
        pets=pets,
    )


async def _build_pet_info_message(pet: PetORM) -> MessageFactory:
    pic_bytes = await render_custom_pet_info(pet)
    msg = MessageFactory()
    msg += Image(pic_bytes)
    return msg

mintmark_matcher = matcher_group.on_message(
    rule=startswith_or_endswith("刻印") & no_reply()
)


@mintmark_matcher.handle()
async def _handle_mintmark(
    matcher: Matcher,
    state: T_State,
    event: Event,
    mintmarks: tuple[
        upstream_mintmark.MintmarkORM,
        ...,
    ] = upstream_mintmark.GetMintmarkData(),
    classes: tuple[
        upstream_mintmark.MintmarkClassCategoryORM,
        ...,
    ] = upstream_mintmark.GetMintmarkClassData(),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="mintmark",
        mintmarks=mintmarks,
        classes=classes,
    )

gem_matcher = matcher_group.on_message(
    rule=startswith_or_endswith("宝石") & no_reply()
)


@gem_matcher.handle()
async def _handle_gem(
    matcher: Matcher,
    state: T_State,
    event: Event,
    categories: tuple[
        upstream_mintmark.GemCategoryORM,
        ...,
    ] = upstream_mintmark.GetGemCategoryData(),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="gem",
        categories=categories,
    )

type_matcher = matcher_group.on_message(
    rule=startswith_or_endswith("属性") & no_reply()
)


@type_matcher.handle()
async def _handle_type(
    matcher: Matcher,
    state: T_State,
    event: Event,
    session: SeerAPISession,
    type_combinations: tuple[
        upstream_type.TypeCombinationORM,
        ...,
    ] = upstream_type.GetTypeCombinationData(),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="type",
        session=session,
        type_combinations=type_combinations,
    )

battle_effect_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        ("异常", "查询异常状态"),
        suffixes="异常",
    )
    & no_reply()
)


@battle_effect_matcher.handle()
async def _handle_battle_effect(
    matcher: Matcher,
    event: Event,
    state: T_State,
    battle_effects: tuple[
        upstream_effect.BattleEffectORM,
        ...,
    ] = upstream_effect.GetBattleEffectData(),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="battle_effect",
        battle_effects=battle_effects,
    )

suit_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        ("套装", "查询套装信息"),
        suffixes="套装",
    )
    & no_reply()
)


@suit_matcher.handle()
async def _handle_suit(
    matcher: Matcher,
    state: T_State,
    event: Event,
    suits: tuple[
        upstream_cloth.SuitORM,
        ...,
    ] = upstream_cloth.GetSuitData(),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="suit",
        suits=suits,
    )

equip_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        ("部件", "查询部件信息"),
        suffixes="部件",
    )
    & no_reply()
)


@equip_matcher.handle()
async def _handle_equip(
    matcher: Matcher,
    state: T_State,
    event: Event,
    equips: tuple[
        upstream_cloth.EquipORM,
        ...,
    ] = upstream_cloth.GetEquipData(),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="equip",
        equips=equips,
    )

title_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        ("称号", "查询称号信息"),
        suffixes="称号",
    )
    & no_reply()
)


@title_matcher.handle()
async def _handle_title(
    matcher: Matcher,
    state: T_State,
    event: Event,
    titles: tuple[
        upstream_cloth.TitlePartORM,
        ...,
    ] = upstream_cloth.GetTitleData(),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="title",
        titles=titles,
    )

peak_pool_matcher = matcher_group.on_fullmatch(
    ("竞技池", "巅峰竞技池", "竞技精灵池", "限制池"),
    rule=no_reply(),
)


@peak_pool_matcher.handle()
async def _handle_peak_pool(
    matcher: Matcher,
    event: Event,
    pools: list[upstream_peak.PeakPoolORM] = Depends(
        upstream_peak._get_standard_limit_pool
    ),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="peak_pool",
        pools=pools,
    )

peak_expert_pool_matcher = matcher_group.on_fullmatch(
    ("专家池", "巅峰专家池", "专家禁用池"),
    rule=no_reply(),
)


@peak_expert_pool_matcher.handle()
async def _handle_peak_expert_pool(
    matcher: Matcher,
    event: Event,
    pools: list[upstream_peak.PeakExpertPoolORM] = Depends(
        upstream_peak._get_expert_ban_pool
    ),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="peak_expert_pool",
        pools=pools,
    )

peak_vote_matcher = matcher_group.on_fullmatch(
    ("巅峰投票", "巅峰票选", "巅峰池票选", "竞技池票选", "限制池票选"),
    rule=no_reply(),
)


@peak_vote_matcher.handle()
async def _handle_peak_vote(
    matcher: Matcher,
    event: Event,
    session: SeerAPISession,
    game: upstream_peak.SeerGame = upstream_peak.GameClient,
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="peak_vote",
        session=session,
        game=game,
    )

peak_suit_matcher = matcher_group.on_fullmatch(
    ("竞技套装榜", "狂野套装榜", "专家套装榜"),
    rule=no_reply(),
)


@peak_suit_matcher.handle()
async def _handle_peak_suit(  # noqa: PLR0913
    matcher: Matcher,
    event: Event,
    seerapi_session: SeerAPISession,
    sessions: upstream_peak.AllSessions,
    type_tuple: upstream_peak._PeakTypeTuple = Depends(upstream_peak._get_peak_type),
    game: upstream_peak.SeerGame = upstream_peak.GameClient,
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="peak_suit",
        seerapi_session=seerapi_session,
        sessions=sessions,
        type_tuple=type_tuple,
        game=game,
    )

peak_title_matcher = matcher_group.on_fullmatch(
    ("竞技称号榜", "狂野称号榜", "专家称号榜"),
    rule=no_reply(),
)


@peak_title_matcher.handle()
async def _handle_peak_title(  # noqa: PLR0913
    matcher: Matcher,
    event: Event,
    seerapi_session: SeerAPISession,
    sessions: upstream_peak.AllSessions,
    type_tuple: upstream_peak._PeakTypeTuple = Depends(upstream_peak._get_peak_type),
    game: upstream_peak.SeerGame = upstream_peak.GameClient,
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="peak_title",
        seerapi_session=seerapi_session,
        sessions=sessions,
        type_tuple=type_tuple,
        game=game,
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
async def _handle_peak_pet(  # noqa: PLR0913
    matcher: Matcher,
    event: Event,
    seerapi_session: SeerAPISession,
    command: Annotated[str, Fullmatch()],
    type_tuple: upstream_peak._PeakTypeTuple = Depends(upstream_peak._get_peak_type),
    expert_pools: list[upstream_peak.PeakExpertPoolORM] = Depends(
        upstream_peak._get_expert_ban_pool
    ),
    game: upstream_peak.SeerGame = upstream_peak.GameClient,
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="peak_pet",
        seerapi_session=seerapi_session,
        command=command,
        type_tuple=type_tuple,
        expert_pools=expert_pools,
        game=game,
    )

peak_user_matcher = matcher_group.on_fullmatch(
    ("竞技段位榜", "狂野段位榜", "专家段位榜"),
    rule=no_reply(),
)


@peak_user_matcher.handle()
async def _handle_peak_user(
    matcher: Matcher,
    event: Event,
    seerapi_session: SeerAPISession,
    type_tuple: upstream_peak._PeakTypeTuple = Depends(upstream_peak._get_peak_type),
    game: upstream_peak.SeerGame = upstream_peak.GameClient,
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="peak_user",
        seerapi_session=seerapi_session,
        type_tuple=type_tuple,
        game=game,
    )

async def _fetch_weekly_preview_image(image_url: str):
    try:
        response = await get_http_origin_client().get(image_url)
        response.raise_for_status()
        return Image(response.content)
    except (HTTPStatusError, RequestError):
        return await PreviewImageGetter.get("")


preview_matcher = matcher_group.on_fullmatch("下周预告", rule=no_reply())


@preview_matcher.handle()
async def _handle_preview(event: Event, session: SeerAPISession) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        action="preview",
        session=session,
    )

data_version_matcher = matcher_group.on_fullmatch("数据版本", rule=no_reply())


@data_version_matcher.handle()
async def _handle_data_version(
    matcher: Matcher,
    event: Event,
    session: SeerAPISession,
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="data_version",
        session=session,
    )
