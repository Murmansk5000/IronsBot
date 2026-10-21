from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.command_catalog import CommandCatalog, CommandContext
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.features import Feature
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, SendResult
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.onebot.context import command_context
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.services.ai.command_contracts import ai_chat_command_contracts
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.pet_config_commands import pet_config_command_contracts
from ironsbot.services.portable_autocard_commands import (
    build_portable_autocard_operations,
)
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_pet_config_commands import (
    build_portable_pet_config_operation,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_reply import deliver_portable_reply
from ironsbot.services.portable_seer_commands import build_portable_seer_operations
from ironsbot.services.seer.autocard import AutocardSearchResult
from ironsbot.services.seer.autocard_sanctuary import SanctuarySearchResult
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.query_result import QueryChoice, QueryReply, QueryResult
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts
from tests.helpers.onebot_events import private_message_event

if TYPE_CHECKING:
    from ironsbot.services.seer.resources import SeerQueryResources

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


def _catalog(
    image_commands: frozenset[str] = frozenset(),
    *,
    operation_ids: frozenset[str] | None = None,
) -> CommandCatalog:
    resolver = PlayerIdResolver(lambda _text, _conversation: None, lambda _actor: None)
    catalog = CommandCatalog()
    contributions = (
        PluginContribution(
            id="seer_query",
            commands=seer_command_contracts(resolver, image_commands=image_commands),
        ),
        PluginContribution(
            id="pet_config",
            commands=pet_config_command_contracts(
                enabled=True, image_commands=image_commands
            ),
        ),
        PluginContribution(
            id="ai_chat", commands=ai_chat_command_contracts(enabled=True)
        ),
        PluginContribution(
            id="rank_help", commands=rank_help_command_contracts(resolver)
        ),
    )
    catalog.load(
        tuple(
            replace(
                plugin,
                commands=tuple(
                    command
                    for command in plugin.commands
                    if operation_ids is None
                    or command.id in operation_ids
                    or command.plugin_id == "ai_chat"
                ),
            )
            for plugin in contributions
        ),
        known_features={feature.value for feature in Feature},
    )
    return catalog


def _empty_query_service(*names: str) -> SimpleNamespace:
    return SimpleNamespace(
        **{name: AsyncMock(return_value=QueryResult()) for name in names}
    )


def _context(text: str, platform: Platform) -> MessageInputContext:
    actor = ActorRef(platform, "100")
    return MessageInputContext(
        IncomingMessageRef(
            platform, actor, ConversationRef(platform, "private", actor.id), "1", text
        ),
        mentions_bot=False,
    )


def _resources() -> SeerQueryResources:
    return cast(
        "SeerQueryResources",
        SimpleNamespace(
            data_queries=SimpleNamespace(),
            external_references=None,
            pet_flip=None,
            team_query=SimpleNamespace(),
            peak_query=SimpleNamespace(),
            pet_query=_empty_query_service(
                "search_info",
                "select_info",
                "search_image",
                "select_image",
                "search_avatar",
                "select_avatar",
            ),
            mintmark=_empty_query_service(
                "search_mintmark", "select_mintmark", "search_gem", "select_gem"
            ),
            equipment=_empty_query_service("search", "select"),
            type_query=_empty_query_service("search", "select"),
            battle_effect=_empty_query_service("search", "select"),
        ),
    )


@pytest.mark.parametrize(
    "text,feature,expected",
    [
        ("精灵盖亚", "seer_pet", "seer.pet.query"),
        ("盖亚技能", "seer_pet", "seer.pet.query"),
        ("魂印盖亚", "seer_pet", "seer.pet.query"),
        ("盖亚立绘", "seer_pet", "seer.pet.image"),
        ("皮肤盖亚", "seer_pet", "seer.pet.image"),
        ("头像盖亚", "seer_pet", "seer.pet.avatar"),
        ("盖亚头像", "seer_pet", "seer.pet.avatar"),
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
    assert (
        not AiInputRoutingService(features, catalog)
        .decide(
            message_input_context(private_message_event(text, user_id=int(_ACTOR.id))),
            command_context(private_message_event(text, user_id=int(_ACTOR.id))),
        )
        .try_chat
    )
    assert not catalog.claims_direct_input(
        context, FeatureService({}, {}, frozenset()), text
    )


@pytest.mark.parametrize(
    "text,command_id,service_name,method_name,arguments",
    [
        ("精灵盖亚技能", "seer.pet.query", "pet_query", "search_info", ("盖亚",)),
        ("盖亚立绘", "seer.pet.image", "pet_query", "search_image", ("盖亚",)),
        ("盖亚头像", "seer.pet.avatar", "pet_query", "search_avatar", ("盖亚",)),
        ("刻印v9", "seer.mintmark.query", "mintmark", "search_mintmark", ("v9",)),
        ("胜利宝石", "seer.mintmark.query", "mintmark", "search_gem", ("胜利",)),
        ("测试套装", "seer.equipment.query", "equipment", "search", ("suit", "测试")),
        ("部件测试", "seer.equipment.query", "equipment", "search", ("equip", "测试")),
        ("称号测试", "seer.equipment.query", "equipment", "search", ("title", "测试")),
        ("水属性", "seer.type.query", "type_query", "search", ("水",)),
        ("异常冻伤", "seer.type.query", "battle_effect", "search", ("冻伤",)),
    ],
)
@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_public_route_parses_affix_and_queries_once(  # noqa: PLR0913
    text: str,
    command_id: str,
    service_name: str,
    method_name: str,
    arguments: tuple[str, ...],
    platform: Platform,
) -> None:
    context = _context(text, platform)
    features = FeatureService({}, {context.message.actor: _QUERY_FEATURES}, frozenset())
    resources = _resources()
    search = getattr(getattr(resources, service_name), method_name)
    search.return_value = QueryResult(reply=QueryReply(text="matched"))
    catalog = _catalog()
    sessions = PortableQuerySessions()
    operations = build_portable_seer_operations(
        catalog,
        resources,
        sessions,
        features,
        PlayerIdResolver(lambda *_: None, lambda _: None),
    )
    ai = Mock(chat_reply=AsyncMock())
    router = PortableCommandRouter(
        _catalog(operation_ids=frozenset(operations)),
        operations,
        features,
        ai=ai,
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )
    assert catalog.get(command_id) is not None
    assert router.recognizes(context)
    reply = await router.dispatch(context)
    assert reply is not None
    assert reply.message == OutboundMessage.from_text("matched")
    search.assert_awaited_once()
    assert search.await_args.args == arguments
    ai.chat_reply.assert_not_awaited()


@pytest.mark.parametrize("text", ["精灵雷伊", "雷伊皮肤", "雷伊配置", "皮肤盖亚"])
def test_configured_exact_images_override_even_help_examples(text: str) -> None:
    features = FeatureService({}, {_ACTOR: _QUERY_FEATURES}, frozenset())
    catalog = _catalog(frozenset({text}))
    context = CommandContext(_ACTOR, _PRIVATE)
    query_ids = {
        "seer.pet.query",
        "seer.pet.image",
        "seer.pet.avatar",
        "pet_config.query",
    }
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


@pytest.mark.parametrize(
    "operation_id,text",
    [
        ("seer.pet.query", "币斯奥技能"),
        ("seer.mintmark.query", "什么时候100块一个刻印"),
        ("seer.mintmark.query", "刻印"),
        ("seer.mintmark.query", "一个刻印"),
        ("seer.equipment.query", "这个套装"),
        ("seer.equipment.query", "部件有问题"),
        ("seer.equipment.query", "他有一个称号"),
        ("seer.type.query", "能不能让他识别属性技能和属性"),
        ("seer.type.query", "这个异常不应该回复异常"),
    ],
)
@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_empty_affix_entity_lookups_stay_silent(
    operation_id: str,
    text: str,
    platform: Platform,
) -> None:
    resolver = PlayerIdResolver(lambda _text, _conversation: None, lambda _actor: None)
    context = _context(text, platform)
    features = FeatureService({}, {context.message.actor: _QUERY_FEATURES}, frozenset())
    catalog = _catalog()
    sessions = PortableQuerySessions()
    operations = build_portable_seer_operations(
        catalog,
        _resources(),
        sessions,
        features,
        resolver,
    )
    ai = Mock(chat_reply=AsyncMock())
    router = PortableCommandRouter(
        _catalog(operation_ids=frozenset(operations)),
        operations,
        features,
        ai=ai,
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )
    assert operation_id in operations
    assert await router.dispatch(context) is None
    ai.chat_reply.assert_not_awaited()


@pytest.mark.parametrize("text", ["精灵榜", "皮肤榜", "群星牌榜", "刻印攻击榜"])
def test_rank_commands_do_not_belong_to_fuzzy_queries(text: str) -> None:
    features = FeatureService({}, {_ACTOR: _QUERY_FEATURES}, frozenset())
    context = CommandContext(_ACTOR, _PRIVATE)
    fuzzy_ids = {
        "seer.pet.query",
        "seer.pet.image",
        "seer.pet.avatar",
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
@pytest.mark.parametrize("platform", list(Platform))
async def test_pet_config_public_route_shares_image_exclusion(
    text: str, platform: Platform, *, reserved: bool
) -> None:
    context = _context(text, platform)
    features = FeatureService({}, {context.message.actor: _QUERY_FEATURES}, frozenset())
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="pet_config",
                commands=pet_config_command_contracts(
                    enabled=True, image_commands=frozenset({"雷伊配置"})
                ),
            ),
        ),
        known_features={"pet_config"},
    )
    sessions = PortableQuerySessions()
    service = Mock(search=AsyncMock(return_value=QueryResult()))
    router = PortableCommandRouter(
        catalog,
        {
            "pet_config.query": build_portable_pet_config_operation(
                service, sessions, image_command_texts=frozenset({"雷伊配置"})
            )
        },
        features,
        ai=Mock(),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )
    assert router.recognizes(context) is not reserved
    assert await router.dispatch(context) is None
    if not reserved:
        service.search.assert_awaited_once_with("盖亚")
    else:
        service.search.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize(
    "text,command_id",
    [
        ("卡牌盖亚", "seer.autocard.query"),
        ("祝印测试", "seer.autocard.sanctuary"),
    ],
)
async def test_autocard_public_route_owns_input_without_ai_fallback(
    text: str, command_id: str, platform: Platform
) -> None:
    context = _context(text, platform)
    features = FeatureService({}, {context.message.actor: _QUERY_FEATURES}, frozenset())
    service = Mock(search=Mock(return_value=AutocardSearchResult()))
    sanctuary = Mock(search=Mock(return_value=SanctuarySearchResult()))
    sessions = PortableQuerySessions()
    operations = build_portable_autocard_operations(
        service, Mock(), sanctuary, sessions
    )
    catalog = _catalog(operation_ids=frozenset(operations))
    ai = Mock(chat_reply=AsyncMock())
    router = PortableCommandRouter(
        catalog,
        operations,
        features,
        ai=ai,
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )
    assert router.recognizes(context)
    assert await router.dispatch(context) is None
    selected = service if command_id == "seer.autocard.query" else sanctuary
    other = sanctuary if selected is service else service
    selected.search.assert_called_once_with(text)
    other.search.assert_not_called()
    ai.chat_reply.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_affix_menu_selection_uses_same_public_route_once(
    platform: Platform,
) -> None:
    context = _context("盖亚技能", platform)
    features = FeatureService({}, {context.message.actor: _QUERY_FEATURES}, frozenset())
    resources = _resources()
    service = cast("SimpleNamespace", resources.pet_query)
    service.search_info.return_value = QueryResult(
        choices=(
            QueryChoice("one", "1", 1),
            QueryChoice("two", "2", 2),
        )
    )
    service.select_info.return_value = QueryResult(reply=QueryReply(text="selected"))
    catalog = _catalog()
    sessions = PortableQuerySessions()
    ai = Mock(chat_reply=AsyncMock())
    operations = build_portable_seer_operations(
        catalog,
        resources,
        sessions,
        features,
        PlayerIdResolver(lambda *_: None, lambda _: None),
    )
    router = PortableCommandRouter(
        _catalog(operation_ids=frozenset(operations)),
        operations,
        features,
        ai=ai,
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )
    reply = await router.dispatch(context)
    assert reply is not None and reply.message.prompt is not None
    send = AsyncMock(return_value=SendResult(delivered=True, message_id="receipt"))
    await deliver_portable_reply(reply, send)
    selected = await router.dispatch(_context("2", platform))
    assert selected is not None
    assert selected.message == OutboundMessage.from_text("selected")
    await deliver_portable_reply(selected, send)
    service.search_info.assert_awaited_once()
    service.select_info.assert_awaited_once()
    assert service.select_info.await_args.args == (2,)
    ai.chat_reply.assert_not_awaited()
