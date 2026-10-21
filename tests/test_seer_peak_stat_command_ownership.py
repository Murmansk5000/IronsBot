from __future__ import annotations

from typing import TYPE_CHECKING
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
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_countermark_commands import (
    build_portable_countermark_operations,
)
from ironsbot.services.portable_data_commands import build_portable_data_operation
from ironsbot.services.portable_reply import deliver_portable_reply
from ironsbot.services.portable_seer_commands import (
    build_peak_query_operation,
    build_peak_rank_operation,
)
from ironsbot.services.seer import rank_list_parsing
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.countermark_stat_rank_messages import (
    build_countermark_stat_rank_message,
)
from ironsbot.services.seer.countermark_stat_rank_parsing import (
    parse_countermark_stat_rank_command,
)
from ironsbot.services.seer.data_query_commands import (
    DATA_VERSION_COMMANDS,
    SEASON_COUNTDOWN_COMMANDS,
    WEEKLY_PREVIEW_COMMANDS,
)
from ironsbot.services.seer.peak import (
    PEAK_EXPERT_POOL_COMMANDS,
    PEAK_MASTER_POOL_COMMANDS,
    PEAK_PET_RANK_COMMANDS,
    PEAK_POOL_COMMANDS,
    PEAK_SUIT_RANK_COMMANDS,
    PEAK_TITLE_RANK_COMMANDS,
    PEAK_VOTE_COMMANDS,
    PeakQueryResult,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.rank_catalog import RANK_COMMAND_MAP
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts
from tests.helpers.onebot_events import private_message_event

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.services.portable_reply import PortableOperation


_ACTOR = ActorRef(Platform.ONEBOT, "100")
_PRIVATE = ConversationRef(Platform.ONEBOT, "private", _ACTOR.id)
_FEATURES = frozenset(
    {"seer_peak", "seer_pet", "seer_mintmark", "seer_rank", "seer_data", "ai_chat"}
)


def _context(text: str, platform: Platform) -> MessageInputContext:
    actor = ActorRef(platform, "100")
    return MessageInputContext(
        IncomingMessageRef(
            platform, actor, ConversationRef(platform, "private", actor.id), "1", text
        ),
        mentions_bot=False,
    )


def _router(
    catalog: CommandCatalog,
    operations: Mapping[str, PortableOperation],
    context: MessageInputContext,
) -> PortableCommandRouter:
    selected = CommandCatalog()
    selected.load(
        (
            PluginContribution(
                id="seer_query",
                commands=tuple(
                    command
                    for id_ in operations
                    if (command := catalog.get(id_)) is not None
                ),
            ),
        ),
        known_features={feature.value for feature in Feature},
    )
    features = FeatureService({}, {context.message.actor: _FEATURES}, frozenset())
    return PortableCommandRouter(
        selected,
        operations,
        features,
        ai=Mock(),
        ai_input_routing=AiInputRoutingService(features, selected),
        addressed_input_hints=AddressedInputHintService(),
    )


@pytest.fixture
def catalog() -> CommandCatalog:
    resolver = PlayerIdResolver(lambda _text, _conversation: None, lambda _actor: None)
    result = CommandCatalog()
    result.load(
        (
            PluginContribution(
                id="seer_query", commands=seer_command_contracts(resolver)
            ),
            PluginContribution(
                id="rank_help", commands=rank_help_command_contracts(resolver)
            ),
        ),
        known_features={feature.value for feature in Feature},
    )
    return result


@pytest.mark.parametrize(
    "text,expected",
    [
        ("限制池", "seer.peak.query"),
        ("巅峰专家池", "seer.peak.query"),
        ("大师池", "seer.peak.query"),
        ("竞技池票选", "seer.peak.query"),
        ("专家套装榜", "seer.peak.rank"),
        ("竞技称号榜", "seer.peak.rank"),
        ("狂野精灵总榜", "seer.peak.rank"),
        ("五角刻印速度榜", "seer.mintmark.rank"),
        ("刻印双防体排行榜", "seer.mintmark.rank"),
        ("刻印攻榜", "seer.mintmark.rank"),
        ("赛季时间", "seer.data.query"),
        ("新增内容", "seer.data.new_content"),
        ("竞技池变化", "seer.peak.query"),
        ("专家池变化", "seer.peak.query"),
        ("大师池变化", "seer.peak.query"),
        ("巅峰环境变化", "seer.data.peak_environment_changes"),
    ],
)
def test_non_example_peak_and_stat_commands_are_owned(
    catalog: CommandCatalog, text: str, expected: str
) -> None:
    features = FeatureService({}, {_ACTOR: _FEATURES}, frozenset())
    context = CommandContext(_ACTOR, _PRIVATE)
    assert [
        command.id
        for command in catalog.available_for_context(context, features)
        if command.matches_direct_input(context, text)
    ] == [expected]
    assert (
        not AiInputRoutingService(features, catalog)
        .decide(
            message_input_context(private_message_event(text, user_id=100)),
            command_context(private_message_event(text, user_id=100)),
        )
        .try_chat
    )


@pytest.mark.parametrize(
    "commands,command_id,method",
    [
        (PEAK_POOL_COMMANDS, "seer.peak.query", "pool"),
        (PEAK_EXPERT_POOL_COMMANDS, "seer.peak.query", "pool"),
        (PEAK_MASTER_POOL_COMMANDS, "seer.peak.query", "master_pool"),
        (PEAK_VOTE_COMMANDS, "seer.peak.query", "vote"),
        (PEAK_SUIT_RANK_COMMANDS, "seer.peak.rank", "item_rank"),
        (PEAK_TITLE_RANK_COMMANDS, "seer.peak.rank", "item_rank"),
        (PEAK_PET_RANK_COMMANDS, "seer.peak.rank", "pet_rank"),
    ],
)
@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_every_peak_alias_runs_public_operation_once(
    catalog: CommandCatalog,
    commands: tuple[str, ...],
    command_id: str,
    method: str,
    platform: Platform,
) -> None:
    service = Mock(
        **{
            name: AsyncMock(return_value=PeakQueryResult(text="matched"))
            for name in ("pool", "master_pool", "vote", "item_rank", "pet_rank")
        }
    )
    operations = {
        "seer.peak.query": build_peak_query_operation(service),
        "seer.peak.rank": build_peak_rank_operation(service),
    }
    disabled = FeatureService({}, {_ACTOR: frozenset({"ai_chat"})}, frozenset())
    for text in commands:
        context = _context(text, platform)
        router = _router(catalog, operations, context)
        assert router.recognizes(context)
        reply = await router.dispatch(context)
        assert reply is not None
        assert reply.message == OutboundMessage.from_text("matched")
        await deliver_portable_reply(
            reply,
            AsyncMock(return_value=SendResult(delivered=True, message_id="receipt")),
        )
        getattr(service, method).assert_awaited_once()
        for name in ("pool", "master_pool", "vote", "item_rank", "pet_rank"):
            if name != method:
                getattr(service, name).assert_not_awaited()
        if method == "pool":
            assert service.pool.await_args.kwargs["expert"] == (
                commands == PEAK_EXPERT_POOL_COMMANDS
            )
        if method == "item_rank":
            assert service.item_rank.await_args.kwargs["kind"] == (
                "套装" if commands == PEAK_SUIT_RANK_COMMANDS else "称号"
            )
        service.reset_mock()
        command_context_ = CommandContext(
            context.message.actor, context.message.conversation
        )
        assert not catalog.claims_direct_input(command_context_, disabled, text)
        contract = catalog.get(command_id)
        assert contract is not None and contract.matches_direct_input(
            command_context_, text
        )
        for invalid in (f"/{text}", f"{text}是什么", f" {text}", " ".join(text)):
            assert not contract.matches_direct_input(command_context_, invalid)
            assert await router.dispatch(_context(invalid, platform)) is None
            for name in ("pool", "master_pool", "vote", "item_rank", "pet_rank"):
                getattr(service, name).assert_not_awaited()


@pytest.mark.parametrize("alias", RANK_COMMAND_MAP)
def test_collection_and_player_rank_aliases_do_not_become_stat_commands(
    alias: str,
) -> None:
    assert rank_list_parsing.parse_rank_list_command(alias) is not None
    assert parse_countermark_stat_rank_command(alias) is None


def test_new_rank_alias_is_excluded_without_editing_a_stat_keyword_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "测试刻印收藏榜"
    monkeypatch.setitem(
        rank_list_parsing._NORMALIZED_COMMANDS, text, ("global", "刻印图鉴")
    )
    assert rank_list_parsing.parse_rank_list_command(text) is not None
    assert parse_countermark_stat_rank_command(text) is None


@pytest.mark.parametrize("text", ["２角刻印攻击排行", "刻印双防体排行榜", "刻印攻榜"])
@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_stat_public_route_passes_shared_parser_result_to_service(
    catalog: CommandCatalog, text: str, platform: Platform
) -> None:
    service = Mock(query=Mock(return_value="stat result"))
    context = _context(text, platform)
    router = _router(catalog, build_portable_countermark_operations(service), context)
    assert router.recognizes(context)
    reply = await router.dispatch(context)
    assert reply is not None and reply.message == OutboundMessage.from_text(
        "stat result"
    )
    parsed = parse_countermark_stat_rank_command(text)
    assert parsed is not None
    service.query.assert_called_once_with(parsed)
    if text == "刻印攻榜":
        assert parsed.stat is None
        assert "需要指定属性" in build_countermark_stat_rank_message(parsed, [])


@pytest.mark.parametrize(
    "text", ["攻击榜", "看看限制池怎么样", "巅峰投票说明", "刻印V9"]
)
def test_unrelated_input_is_not_claimed_by_peak_or_stat_sections(
    catalog: CommandCatalog, text: str
) -> None:
    context = CommandContext(_ACTOR, _PRIVATE)
    features = FeatureService({}, {_ACTOR: _FEATURES}, frozenset())
    expected_ids = {"seer.peak.query", "seer.peak.rank", "seer.mintmark.rank"}
    candidates = [
        c
        for c in catalog.available_for_context(context, features)
        if c.id in expected_ids
    ]
    assert {c.id for c in candidates} == expected_ids
    assert not any(c.matches_direct_input(context, text) for c in candidates)


@pytest.mark.parametrize(
    "commands,method",
    [
        (WEEKLY_PREVIEW_COMMANDS, "weekly_preview"),
        (DATA_VERSION_COMMANDS, "data_version"),
        (SEASON_COUNTDOWN_COMMANDS, "season_countdown"),
    ],
)
@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_data_aliases_run_public_service_once(
    catalog: CommandCatalog, commands: tuple[str, ...], method: str, platform: Platform
) -> None:
    service = Mock(
        **{
            name: AsyncMock(return_value="data result")
            for name in ("weekly_preview", "data_version", "season_countdown")
        }
    )
    for text in commands:
        context = _context(text, platform)
        router = _router(
            catalog,
            {"seer.data.query": build_portable_data_operation(service)},
            context,
        )
        assert router.recognizes(context)
        reply = await router.dispatch(context)
        assert reply is not None
        assert reply.message == OutboundMessage.from_text("data result")
        getattr(service, method).assert_awaited_once()
        for name in ("weekly_preview", "data_version", "season_countdown"):
            if name != method:
                getattr(service, name).assert_not_awaited()
        service.reset_mock()
