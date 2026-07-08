# SPDX-License-Identifier: GPL-3.0-or-later
"""High-priority entry points for upstream Seer info queries.

These matchers keep upstream query behavior available through the Seer query
adapter without editing upstream-derived handlers and renderers. They register
at the feature plugin priority so they win before lower-priority matchers.
"""

from typing import Annotated

from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.params import Depends, Fullmatch
from nonebot.rule import Rule
from nonebot.typing import T_State
from seerapi_models import PetORM

from ironsbot.services.seer.query_guards import is_rank_query_text
from ironsbot.services.sendpic_fixed_image import FIXED_IMAGE_COMMANDS
from ironsbot.shared.plugin_system import (
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..depends import (
    GetPetData,
    SeerAPISession,
)
from ..group import matcher_group, seer_feature_priority, seer_feature_rule
from ..prompt import (
    PromptItem,
)
from ..upstream_commands import cloth as upstream_cloth
from ..upstream_commands import effect as upstream_effect
from ..upstream_commands import mintmark as upstream_mintmark
from ..upstream_commands import peak as upstream_peak
from ..upstream_commands import pet as upstream_pet
from ..upstream_commands import type as upstream_type
from .upstream_plugin import UPSTREAM_QUERY_PLUGIN_NAME, UpstreamQueryPlugin


async def _is_not_rank_query(event: Event) -> bool:
    return not is_rank_query_text(event.get_plaintext())


not_rank_query = Rule(_is_not_rank_query)


async def _is_not_fixed_image_command(event: Event) -> bool:
    return event.get_plaintext().strip() not in FIXED_IMAGE_COMMANDS


not_fixed_image_command = Rule(_is_not_fixed_image_command)


pet_image_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_pet")
    & startswith_or_endswith(
        prefixes=("立绘", "皮肤", "查询立绘"),
    )
    & not_rank_query
    & not_fixed_image_command
    & no_reply(),
    priority=seer_feature_priority("seer_pet"),
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

pet_info_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_pet")
    & startswith_or_endswith(
        prefixes=("精灵", "查询精灵信息", "魂印", "技能"),
        suffixes=("查询精灵信息", "魂印", "技能"),
    )
    & not_rank_query
    & not_fixed_image_command
    & no_reply(),
    priority=seer_feature_priority("seer_pet"),
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


mintmark_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_mintmark")
    & startswith_or_endswith("刻印")
    & not_rank_query
    & no_reply(),
    priority=seer_feature_priority("seer_mintmark"),
)


@mintmark_matcher.handle()
async def _handle_mintmark(  # noqa: PLR0913
    matcher: Matcher,
    state: T_State,
    event: Event,
    arg: str = Depends(parse_string_arg),
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
        arg=arg,
        mintmarks=mintmarks,
        classes=classes,
    )

gem_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_mintmark")
    & startswith_or_endswith("宝石")
    & no_reply(),
    priority=seer_feature_priority("seer_mintmark"),
)


@gem_matcher.handle()
async def _handle_gem(
    matcher: Matcher,
    state: T_State,
    event: Event,
    arg: str = Depends(parse_string_arg),
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
        arg=arg,
        categories=categories,
    )

type_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_type")
    & startswith_or_endswith("属性")
    & no_reply(),
    priority=seer_feature_priority("seer_type"),
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
    rule=seer_feature_rule("seer_type")
    & startswith_or_endswith(
        ("异常", "查询异常状态"),
        suffixes="异常",
    )
    & no_reply(),
    priority=seer_feature_priority("seer_type"),
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
    rule=seer_feature_rule("seer_equipment")
    & startswith_or_endswith(
        ("套装", "查询套装信息"),
        suffixes="套装",
    )
    & not_rank_query
    & no_reply(),
    priority=seer_feature_priority("seer_equipment"),
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
    rule=seer_feature_rule("seer_equipment")
    & startswith_or_endswith(
        ("部件", "查询部件信息"),
        suffixes="部件",
    )
    & not_rank_query
    & no_reply(),
    priority=seer_feature_priority("seer_equipment"),
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
    rule=seer_feature_rule("seer_equipment")
    & startswith_or_endswith(
        ("称号", "查询称号信息"),
        suffixes="称号",
    )
    & not_rank_query
    & no_reply(),
    priority=seer_feature_priority("seer_equipment"),
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
    rule=seer_feature_rule("seer_peak") & no_reply(),
    priority=seer_feature_priority("seer_peak"),
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
    rule=seer_feature_rule("seer_peak") & no_reply(),
    priority=seer_feature_priority("seer_peak"),
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
    rule=seer_feature_rule("seer_peak") & no_reply(),
    priority=seer_feature_priority("seer_peak"),
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
    rule=seer_feature_rule("seer_peak") & no_reply(),
    priority=seer_feature_priority("seer_peak"),
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
    rule=seer_feature_rule("seer_peak") & no_reply(),
    priority=seer_feature_priority("seer_peak"),
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
    rule=seer_feature_rule("seer_peak") & no_reply(),
    priority=seer_feature_priority("seer_peak"),
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
    rule=seer_feature_rule("seer_peak") & no_reply(),
    priority=seer_feature_priority("seer_peak"),
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

preview_matcher = matcher_group.on_fullmatch(
    "下周预告",
    rule=seer_feature_rule("seer_data") & no_reply(),
    priority=seer_feature_priority("seer_data"),
)


@preview_matcher.handle()
async def _handle_preview(
    matcher: Matcher,
    event: Event,
    session: SeerAPISession,
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="preview",
        session=session,
    )

data_version_matcher = matcher_group.on_fullmatch(
    "数据版本",
    rule=seer_feature_rule("seer_data") & no_reply(),
    priority=seer_feature_priority("seer_data"),
)


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


season_countdown_matcher = matcher_group.on_fullmatch(
    ("赛季倒计时", "赛季时间", "赛季结束", "赛季"),
    rule=seer_feature_rule("seer_data") & no_reply(),
    priority=seer_feature_priority("seer_data"),
)


@season_countdown_matcher.handle()
async def _handle_season_countdown(
    matcher: Matcher,
    event: Event,
    session: SeerAPISession,
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="season_countdown",
        session=session,
    )
