from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import nonebot
import pytest
from nonebot.rule import Rule, fullmatch

from ironsbot.config.models.messaging import MessageConfig
from ironsbot.core.command_catalog import (
    CommandCatalog,
    CommandContext,
    CommandContract,
)
from ironsbot.core.commands import command_text_matches
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.plugins.onebot.ai import AI_CHAT_PROMPT_KEY, _capture_ai_prompt
from ironsbot.plugins.onebot.bilibili.command_rules import (
    is_bili_account_command,
    is_dynamic_menu_command,
)
from ironsbot.services.about_commands import about_command_contracts
from ironsbot.services.bilibili.command_contracts import bilibili_command_contracts
from ironsbot.services.help_commands import help_command_contracts
from ironsbot.services.messaging.command_contracts import messaging_command_contracts
from ironsbot.services.messaging.meeting import meeting_command_contracts
from ironsbot.services.messaging.service import find_command_action
from ironsbot.services.operations.docker_commands import docker_command_contracts
from ironsbot.services.operations.server_status_commands import (
    server_status_command_contracts,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts
from ironsbot.services.team.resource_commands import team_resource_command_contracts
from tests.helpers.onebot_events import private_message_event

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

ACTOR = ActorRef(Platform.ONEBOT, "100")
PRIVATE = ConversationRef(Platform.ONEBOT, "private", ACTOR.id)
CONTEXT = CommandContext(ACTOR, PRIVATE)
FEATURES = FeatureService(
    {},
    {
        ACTOR: frozenset(
            {
                "help",
                "about",
                "seer_rank",
                "server_status_query",
                "ai_chat",
                "text",
                "meeting",
                "bili_query",
                "bili_push",
                "team_resource_subscription",
            }
        )
    },
    frozenset({ACTOR}),
)


def _fixed_contracts() -> tuple[CommandContract, ...]:
    resolver = PlayerIdResolver(lambda _text, _conversation: None, lambda _actor: None)
    return (
        *help_command_contracts(),
        *about_command_contracts(),
        *docker_command_contracts(),
        *server_status_command_contracts(),
        *(
            c
            for c in rank_help_command_contracts(resolver)
            if c.routing_matcher is None
        ),
    )


@pytest.mark.parametrize("contract", _fixed_contracts(), ids=lambda c: c.id)
@pytest.mark.asyncio
async def test_fixed_contracts_match_literal_fullmatch(
    contract: CommandContract,
) -> None:
    names = (*contract.examples, *contract.routing_aliases)
    rule = fullmatch(names)
    for name in names:
        for text in (name, " " + name, name + "\t", " ".join(name), "/" + name):
            event = private_message_event(text, user_id=100)
            assert contract.matches_direct_input(CONTEXT, text) == await rule(
                cast("Bot", None), event, {}
            )


@pytest.mark.asyncio
async def test_help_about_installed_rules_and_ai_use_original_text() -> None:
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    from ironsbot.plugins.onebot import about
    from ironsbot.plugins.onebot import help as help_plugin

    registry = Mock()
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(id="help", commands=help_command_contracts()),
            PluginContribution(id="about", commands=about_command_contracts()),
        ),
        known_features={"help", "about"},
    )
    about.install(registry)
    help_plugin.install(registry, Mock(), FEATURES, catalog, ignored_plugins=())
    for call in registry.on_fullmatch.call_args_list:
        name = call.args[0]
        rule = fullmatch(name) & cast("Rule", call.kwargs["rule"])
        for text in (name, " " + name, name + " ", " ".join(name)):
            event = private_message_event(text, user_id=100)
            actual = await rule(cast("Bot", None), event, {})
            assert catalog.claims_direct_input(CONTEXT, FEATURES, text) == actual
            state = {}
            assert _capture_ai_prompt(event, state, FEATURES, catalog) is not actual
            if not actual:
                assert state[AI_CHAT_PROMPT_KEY] == text.strip()


def _normalized_contracts() -> tuple[CommandContract, ...]:
    config = MessageConfig.model_validate(
        {
            "commands": [
                {
                    "id": "example",
                    "commands": ["Hello World"],
                    "message": "reply",
                    "feature": "text",
                }
            ]
        }
    )
    return (
        *messaging_command_contracts(config),
        *meeting_command_contracts(("Meeting",)),
        *bilibili_command_contracts(),
        *team_resource_command_contracts(enabled=True, query_commands=("Team",)),
    )


@pytest.mark.parametrize(
    "id_,name,text",
    [
        ("messaging.example", "Hello World", " h E L L O w O R L D "),
        ("messaging.push_subscription", "td", " T D "),
        ("messaging.push_time", "推送时间", "推 送时间"),
        ("meeting", "Meeting", " M E E T I N G "),
        ("bilibili.dynamic", "动态", " 动 态 "),
        ("bilibili.accounts", "B站账户", " b 站 账 户 "),
        ("team_resource.query", "Team", " T E A M "),
    ],
)
def test_explicit_normalization_keeps_existing_domain_language(
    id_: str, name: str, text: str
) -> None:
    contract = next(c for c in _normalized_contracts() if c.id == id_)
    assert contract.routing_matcher is not None
    assert contract.matches_direct_input(CONTEXT, text) == command_text_matches(
        text, (name,)
    )
    assert contract.matches_direct_input(CONTEXT, text)
    assert not contract.matches_direct_input(CONTEXT, "/" + text)
    event = private_message_event(text, user_id=100)
    if id_ == "bilibili.dynamic":
        assert is_dynamic_menu_command(FEATURES, event)
    if id_ == "bilibili.accounts":
        assert is_bili_account_command(FEATURES, event)
    if id_ == "messaging.example":
        config = MessageConfig.model_validate(
            {
                "commands": [
                    {
                        "id": "example",
                        "commands": [name],
                        "message": "reply",
                        "feature": "text",
                    }
                ]
            }
        )
        assert (
            find_command_action(text, config.commands, is_allowed=lambda _feature: True)
            is not None
        )


@pytest.mark.asyncio
async def test_meeting_installed_rule_preserves_normalization() -> None:
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    from ironsbot.plugins.onebot.messaging import meeting

    registry = Mock()
    meeting.install(registry, ("Meeting",), "", "{meeting_number}", FEATURES)
    rule = cast("Rule", registry.on_message.call_args.kwargs["rule"])
    contract = meeting_command_contracts(("Meeting",))[0]
    for text in ("Meeting", " mEeTing ", "M E E T I N G", "/Meeting", "Meeting X"):
        event = private_message_event(text, user_id=100)
        assert contract.matches_direct_input(CONTEXT, text) == await rule(
            cast("Bot", None), event, {}
        )
