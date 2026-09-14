from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import nonebot
import pytest

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.core.command_catalog import CommandCatalog, CommandContext
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.features import Feature
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.onebot.rules import BOT_COMMAND_ARG_KEY
from ironsbot.plugins.onebot import pet_config as pet_config_plugin
from ironsbot.plugins.onebot.ai import _capture_ai_prompt
from ironsbot.plugins.onebot.seer.query.commands import (
    autocard,
    autocard_sanctuary,
    equipment_queries,
    mintmark_queries,
    pet_queries,
    team,
    type_queries,
)
from ironsbot.plugins.onebot.seer.query.group import SeerMatcherGroup
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.pet_config_commands import pet_config_command_contracts
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from tests.helpers.onebot_events import private_message_event

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot.adapters.onebot.v11 import Bot
    from nonebot.rule import Rule

_ACTOR = ActorRef(Platform.ONEBOT, "100")
_PRIVATE = ConversationRef(Platform.ONEBOT, "private", _ACTOR.id)
_QUERY_FEATURES = frozenset(
    {
        "seer_pet",
        "seer_team",
        "seer_mintmark",
        "seer_equipment",
        "seer_type",
        "seer_autocard",
        "pet_config",
        "ai_chat",
    }
)


def _catalog(image_commands: frozenset[str] = frozenset()) -> CommandCatalog:
    resolver = PlayerIdResolver(lambda _text, _conversation: None, lambda _actor: None)
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="seer_query",
                commands=seer_command_contracts(
                    resolver, image_commands=image_commands
                ),
            ),
            PluginContribution(
                id="pet_config",
                commands=pet_config_command_contracts(
                    enabled=True, image_commands=image_commands
                ),
            ),
        ),
        known_features={feature.value for feature in Feature},
    )
    return catalog


@pytest.mark.parametrize(
    "text,feature,expected",
    [
        ("精灵盖亚", "seer_pet", "seer.pet.query"),
        ("盖亚技能", "seer_pet", "seer.pet.query"),
        ("魂印盖亚", "seer_pet", "seer.pet.query"),
        ("盖亚立绘", "seer_pet", "seer.pet.image"),
        ("皮肤盖亚", "seer_pet", "seer.pet.image"),
        ("刻印V9", "seer_mintmark", "seer.mintmark.query"),
        ("胜利宝石", "seer_mintmark", "seer.mintmark.query"),
        ("查询套装信息测试", "seer_equipment", "seer.equipment.query"),
        ("测试部件", "seer_equipment", "seer.equipment.query"),
        ("称号测试", "seer_equipment", "seer.equipment.query"),
        ("属性水", "seer_type", "seer.type.query"),
        ("冻伤异常", "seer_type", "seer.type.query"),
        ("战队7654321", "seer_team", "seer.team.query"),
        ("卡牌盖亚", "seer_autocard", "seer.autocard.query"),
        ("祝印测试", "seer_autocard", "seer.autocard.sanctuary"),
        ("盖亚配置", "pet_config", "pet_config.query"),
    ],
)
def test_affix_catalog_and_private_ai_ownership(
    text: str, feature: str, expected: str
) -> None:
    catalog = _catalog()
    features = FeatureService(
        {}, {_ACTOR: frozenset({feature, "ai_chat"})}, frozenset()
    )
    context = CommandContext(_ACTOR, _PRIVATE)
    assert [
        command.id
        for command in catalog.available_for_context(context, features)
        if command.matches_direct_input(context, text)
    ] == [expected]
    assert not _capture_ai_prompt(
        private_message_event(text, user_id=int(_ACTOR.id)),
        {},
        AiInputRoutingService(features, catalog),
    )
    assert not catalog.claims_direct_input(
        context, FeatureService({}, {}, frozenset()), text
    )


@pytest.mark.parametrize(
    "install,index,text,argument,command_id",
    [
        (pet_queries.install, 1, "精灵盖亚技能", "盖亚", "seer.pet.query"),
        (pet_queries.install, 0, "盖亚立绘", "盖亚", "seer.pet.image"),
        (mintmark_queries.install, 0, "刻印v9", "v9", "seer.mintmark.query"),
        (mintmark_queries.install, 1, "胜利宝石", "胜利", "seer.mintmark.query"),
        (equipment_queries.install, 0, "测试套装", "测试", "seer.equipment.query"),
        (equipment_queries.install, 1, "部件测试", "测试", "seer.equipment.query"),
        (equipment_queries.install, 2, "称号测试", "测试", "seer.equipment.query"),
        (type_queries.install, 0, "水属性", "水", "seer.type.query"),
        (type_queries.install, 1, "异常冻伤", "冻伤", "seer.type.query"),
        (team.install, 0, "战队7654321", "7654321", "seer.team.query"),
        (autocard.install, 0, "卡牌盖亚", "盖亚", "seer.autocard.query"),
        (autocard_sanctuary.install, 0, "祝印测试", "测试", "seer.autocard.sanctuary"),
    ],
)
@pytest.mark.asyncio
async def test_actual_installed_query_rule_uses_catalog_grammar(
    install: Callable[[SeerMatcherGroup], None],
    index: int,
    text: str,
    argument: str,
    command_id: str,
) -> None:
    features = FeatureService({}, {_ACTOR: _QUERY_FEATURES}, frozenset())
    group = Mock(spec=SeerMatcherGroup)
    group.resources = Mock()
    group.features = features
    group.image_command_texts = frozenset()
    install(group)
    rule = cast("Rule", group.on_message.call_args_list[index].kwargs["rule"])
    state = {}
    assert await rule(
        cast("Bot", None), private_message_event(text, user_id=100), state
    )
    assert state[BOT_COMMAND_ARG_KEY] == argument
    context = CommandContext(_ACTOR, _PRIVATE)
    command = next(
        c
        for c in _catalog().available_for_context(context, features)
        if c.id == command_id
    )
    assert command.matches_direct_input(context, text)


@pytest.mark.parametrize("text", ["精灵雷伊", "雷伊皮肤", "雷伊配置", "皮肤盖亚"])
def test_configured_exact_images_override_even_help_examples(text: str) -> None:
    features = FeatureService({}, {_ACTOR: _QUERY_FEATURES}, frozenset())
    catalog = _catalog(frozenset({text}))
    context = CommandContext(_ACTOR, _PRIVATE)
    query_ids = {"seer.pet.query", "seer.pet.image", "pet_config.query"}
    assert not any(
        c.matches_direct_input(context, text)
        for c in catalog.available_for_context(context, features)
        if c.id in query_ids
    )


@pytest.mark.parametrize(
    "text",
    [
        "我想聊聊精灵",
        "看看雷伊技能怎么样",
        "战队",
        "战队资源",
        "/精灵盖亚",
    ],
)
def test_non_command_input_is_not_claimed(text: str) -> None:
    features = FeatureService({}, {_ACTOR: _QUERY_FEATURES}, frozenset())
    assert not _catalog().claims_direct_input(
        CommandContext(_ACTOR, _PRIVATE), features, text
    )


@pytest.mark.parametrize("text", ["精灵榜", "皮肤榜", "群星牌榜", "刻印攻击榜"])
def test_rank_commands_do_not_belong_to_fuzzy_queries(text: str) -> None:
    features = FeatureService({}, {_ACTOR: _QUERY_FEATURES}, frozenset())
    context = CommandContext(_ACTOR, _PRIVATE)
    fuzzy_ids = {
        "seer.pet.query",
        "seer.pet.image",
        "seer.autocard.query",
        "seer.mintmark.query",
    }
    assert not any(
        c.matches_direct_input(context, text)
        for c in _catalog().available_for_context(context, features)
        if c.id in fuzzy_ids
    )


@pytest.mark.parametrize("text,reserved", [("盖亚配置", False), ("雷伊配置", True)])
@pytest.mark.asyncio
async def test_pet_config_actual_rule_shares_image_exclusion(
    text: str, *, reserved: bool
) -> None:
    features = FeatureService({}, {_ACTOR: _QUERY_FEATURES}, frozenset())
    registry = Mock()
    pet_config_plugin.install(
        registry,
        Mock(),
        features,
        enabled=True,
        image_command_texts=frozenset({"雷伊配置"}),
    )
    rule = cast("Rule", registry.on_message.call_args.kwargs["rule"])
    state = {}
    assert (
        await rule(cast("Bot", None), private_message_event(text, user_id=100), state)
        is not reserved
    )
    if not reserved:
        assert state[BOT_COMMAND_ARG_KEY] == "盖亚"
