from __future__ import annotations

import pytest

from ironsbot.core.command_catalog import CommandCatalog, CommandContext
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.plugins.onebot import lucky_skin_window as lucky_plugin
from ironsbot.plugins.onebot.ai import _capture_ai_prompt
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.bilibili.command_contracts import bilibili_command_contracts
from ironsbot.services.seer.lucky_skin_commands import (
    LUCKY_SKIN_WATCH_CLEAR_COMMANDS,
    LUCKY_SKIN_WATCH_LIST_COMMANDS,
    LUCKY_SKIN_WATCH_REMOVE_COMMANDS,
    LUCKY_SKIN_WATCH_RESET_COMMANDS,
    lucky_skin_window_command_contracts,
)
from ironsbot.services.team.resource_commands import team_resource_command_contracts
from tests.helpers.onebot_events import private_message_event

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
    assert not _capture_ai_prompt(
        private_message_event(text, user_id=int(_ACTOR.id)),
        {},
        AiInputRoutingService(features, catalog),
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command_id,text",
    [
        (command.id, example)
        for command in lucky_skin_window_command_contracts()
        for example in command.examples
    ],
)
async def test_each_lucky_skin_example_matches_the_actual_entry(
    catalog: CommandCatalog, command_id: str, text: str
) -> None:
    features = FeatureService({}, {_ACTOR: _FEATURES}, frozenset())
    event = private_message_event(text, user_id=int(_ACTOR.id))
    context = CommandContext(_ACTOR, _PRIVATE)
    actual = []
    if await lucky_plugin._matches_query(event, {}, features=features):
        actual.append("seer.lucky_skin_window.query")
    for action, commands in (
        ("list", LUCKY_SKIN_WATCH_LIST_COMMANDS),
        ("clear", LUCKY_SKIN_WATCH_CLEAR_COMMANDS),
        ("reset", LUCKY_SKIN_WATCH_RESET_COMMANDS),
    ):
        if await lucky_plugin._matches_watch_exact(
            event, {}, commands=commands, features=features
        ):
            actual.append(f"seer.lucky_skin_window.watch.{action}")
    for action, commands in (
        ("add", LUCKY_SKIN_WATCH_LIST_COMMANDS),
        ("remove", LUCKY_SKIN_WATCH_REMOVE_COMMANDS),
    ):
        if await lucky_plugin._matches_watch_change(
            event, {}, commands=commands, features=features
        ):
            actual.append(f"seer.lucky_skin_window.watch.{action}")
    assert actual == [command_id]
    assert [
        command.id
        for command in catalog.available_for_context(context, features)
        if command.matches_direct_input(context, text)
    ] == actual
