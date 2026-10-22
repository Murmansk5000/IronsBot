from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.command_catalog import CommandCatalog, CommandContext
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, SendResult
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.bilibili.command_contracts import bilibili_command_contracts
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_reply import deliver_portable_reply
from ironsbot.services.seer.lucky_skin_commands import (
    lucky_skin_window_command_contracts,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.team.resource_commands import team_resource_command_contracts
from tests.helpers.onebot_events import group_message_event, private_message_event
from tests.helpers.onebot_inputs import command_context, message_input_context

_ACTOR = ActorRef(Platform.ONEBOT, "100")
_GROUP = ConversationRef(Platform.ONEBOT, "group", "200")
_PRIVATE = ConversationRef(Platform.ONEBOT, "private", _ACTOR.id)
_FEATURES = frozenset(
    {
        "bili_query",
        "bili_push",
        "lucky_skin_window",
        "team_resource_subscription",
        "ai_chat",
    }
)


@pytest.fixture
def catalog() -> CommandCatalog:
    result = CommandCatalog()
    result.load(
        (
            PluginContribution(id="bilibili", commands=bilibili_command_contracts()),
            PluginContribution(
                id="lucky_skin_window", commands=lucky_skin_window_command_contracts()
            ),
            PluginContribution(
                id="team_resource",
                commands=team_resource_command_contracts(
                    enabled=True, query_commands=("战队",)
                ),
            ),
        ),
        known_features=_FEATURES,
    )
    return result


@pytest.mark.parametrize(
    "text,expected",
    [
        ("B站推送模式 example 链接", "bilibili.private_push_mode"),
        ("/b站动态模式 example 内容", "bilibili.private_push_mode"),
        ("B站推送模式", "bilibili.private_push_mode"),
        ("B站账户", "bilibili.accounts"),
        ("订阅战队987654", "team_resource.subscribe"),
        ("添加战队987654 500", "team_resource.subscribe"),
        ("删除订阅战队987654", "team_resource.unsubscribe"),
        ("本群战队", "team_resource.list"),
        ("订阅战队", "team_resource.list"),
        ("幸运橱窗", "seer.lucky_skin_window.query"),
        ("订阅橱窗", "seer.lucky_skin_window.watch.list"),
        ("橱窗关注", "seer.lucky_skin_window.watch.list"),
        ("关注橱窗1400123", "seer.lucky_skin_window.watch.add"),
        ("橱窗订阅 测试皮肤", "seer.lucky_skin_window.watch.add"),
        ("退订橱窗1400123", "seer.lucky_skin_window.watch.remove"),
        ("清空橱窗订阅", "seer.lucky_skin_window.watch.clear"),
        ("重置橱窗关注", "seer.lucky_skin_window.watch.reset"),
    ],
)
def test_subscription_commands_are_claimed_once_and_not_by_ai(
    catalog: CommandCatalog,
    text: str,
    expected: str,
) -> None:
    features = FeatureService({_GROUP: _FEATURES}, {_ACTOR: _FEATURES}, frozenset())
    context = CommandContext(_ACTOR, _PRIVATE)
    assert [
        c.id
        for c in catalog.available_for_context(context, features)
        if c.matches_direct_input(context, text)
    ] == [expected]
    assert (
        not AiInputRoutingService(features, catalog)
        .decide(
            message_input_context(private_message_event(text, user_id=int(_ACTOR.id))),
            command_context(private_message_event(text, user_id=int(_ACTOR.id))),
        )
        .try_chat
    )


@pytest.mark.parametrize(
    "text", ["订阅战队987654", "取消订阅战队987654", "B站推送模式 example 链接"]
)
@pytest.mark.parametrize("role", ["member", "admin", "owner"])
def test_subscription_mutations_respect_group_roles(
    catalog: CommandCatalog,
    text: str,
    role: str,
) -> None:
    features = FeatureService({_GROUP: _FEATURES}, {}, frozenset())
    assert catalog.claims_direct_input(
        CommandContext(_ACTOR, _GROUP, role), features, text
    ) is (role != "member")


def test_team_list_is_read_only_for_regular_members(catalog: CommandCatalog) -> None:
    features = FeatureService({_GROUP: _FEATURES}, {}, frozenset())
    assert catalog.claims_direct_input(
        CommandContext(_ACTOR, _GROUP, "member"), features, "本群战队"
    )


def test_subscription_commands_do_not_claim_disabled_or_unrelated_input(
    catalog: CommandCatalog,
) -> None:
    context = CommandContext(_ACTOR, _PRIVATE)
    disabled = FeatureService({}, {}, frozenset())
    enabled = FeatureService({}, {_ACTOR: _FEATURES}, frozenset())
    for text in ("订阅战队987654", "关注橱窗1400123", "B站推送模式 example 链接"):
        assert not catalog.claims_direct_input(context, disabled, text)
    for text in ("我想聊聊订阅", "/关注橱窗1400123", "清空橱窗关注然后呢"):
        assert not catalog.claims_direct_input(context, enabled, text)


def test_lucky_window_chat_with_member_mention_is_not_a_query() -> None:
    resolver = PlayerIdResolver(
        lambda reference, _conversation: 700001 if reference == "测试玩家" else None,
        lambda _actor: None,
    )
    event = group_message_event(
        message=Message([MessageSegment.at(456), MessageSegment.text(" 橱窗发了吗")]),
        group_id=int(_GROUP.id),
    )
    contract = lucky_skin_window_command_contracts(resolver.has_known_reference)[0]
    context = command_context(event)
    assert context.member_mentions == (ActorRef(Platform.ONEBOT, "456"),)
    assert not contract.matches_direct_input(context, "橱窗发了吗")
    assert contract.matches_direct_input(context, "橱窗")
    assert contract.matches_direct_input(context, "橱窗测试玩家")
    assert contract.matches_direct_input(context, "橱窗700001")
    exact_alias = lucky_skin_window_command_contracts(
        lambda reference, _actor, _conversation: reference == "发了吗"
    )[0]
    assert exact_alias.matches_direct_input(context, "橱窗发了吗")


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize(
    "command_id,text",
    [
        (command.id, example)
        for command in lucky_skin_window_command_contracts()
        for example in command.examples
    ],
)
async def test_each_lucky_skin_example_matches_the_actual_entry(
    catalog: CommandCatalog,
    command_id: str,
    text: str,
    platform: Platform,
    *,
    private: bool,
) -> None:
    actor = ActorRef(platform, "100")
    conversation = ConversationRef(
        platform, "private" if private else "group", actor.id if private else "200"
    )
    context = MessageInputContext(
        IncomingMessageRef(platform, actor, conversation, "event-1", text),
        mentions_bot=False,
    )
    features = FeatureService(
        {conversation: _FEATURES} if not private else {},
        {actor: _FEATURES},
        frozenset(),
    )
    operations = {
        command_id: AsyncMock(return_value=OutboundMessage.from_text(command_id))
        for command_id in catalog.direct_command_ids
    }
    router = PortableCommandRouter(
        catalog,
        operations,
        features,
        ai=Mock(),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
    )
    assert router.recognizes(context)
    reply = await router.dispatch(context)
    assert reply is not None
    await deliver_portable_reply(
        reply,
        AsyncMock(return_value=SendResult(delivered=True, message_id="receipt-1")),
    )
    assert [key for key, operation in operations.items() if operation.await_count] == [
        command_id
    ]
    operations[command_id].assert_awaited_once_with(text, context)
    assert [
        command.id
        for command in catalog.available_for_context(
            CommandContext(actor, conversation), features
        )
        if command.matches_direct_input(CommandContext(actor, conversation), text)
    ] == [command_id]
