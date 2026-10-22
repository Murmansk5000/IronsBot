from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.rule import fullmatch

from ironsbot.config.models.messaging import MessageConfig
from ironsbot.core.command_catalog import (
    CommandCatalog,
    CommandContext,
    CommandContract,
)
from ironsbot.core.commands import command_text_matches
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.services.about import about_command_contracts
from ironsbot.services.ai.command_contracts import ai_chat_command_contracts
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.bilibili.command_contracts import bilibili_command_contracts
from ironsbot.services.help_commands import help_command_contracts
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.messaging.command_contracts import messaging_command_contracts
from ironsbot.services.messaging.meeting import meeting_command_contracts
from ironsbot.services.messaging.service import find_command_action
from ironsbot.services.operations.docker_commands import docker_command_contracts
from ironsbot.services.operations.server_status_commands import (
    server_status_command_contracts,
)
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts
from ironsbot.services.team.resource_commands import team_resource_command_contracts
from tests.helpers.onebot_events import private_message_event
from tests.helpers.onebot_inputs import message_input_context

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
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("name", ["帮助", "关于"])
@pytest.mark.parametrize("shape", ["literal", "leading", "trailing", "middle", "slash"])
async def test_public_route_and_ai_obey_literal_command_ownership(
    platform: Platform, name: str, shape: str
) -> None:
    text = {
        "literal": name,
        "leading": " " + name,
        "trailing": name + " ",
        "middle": " ".join(name),
        "slash": "/" + name,
    }[shape]
    actor = ActorRef(platform, "100")
    conversation = ConversationRef(platform, "private", actor.id)
    context = MessageInputContext(
        IncomingMessageRef(platform, actor, conversation, "1", text), mentions_bot=False
    )
    features = FeatureService(
        {}, {actor: frozenset({"help", "about", "ai_chat"})}, frozenset()
    )
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(id="help", commands=help_command_contracts()),
            PluginContribution(id="about", commands=about_command_contracts()),
            PluginContribution(
                id="ai_chat",
                commands=ai_chat_command_contracts(enabled=True),
            ),
        ),
        known_features={"help", "about", "ai_chat"},
    )
    operation = AsyncMock(return_value=OutboundMessage.from_text("command"))
    ai = Mock(chat_reply=AsyncMock(return_value="chat"))
    routing = AiInputRoutingService(features, catalog)
    router = PortableCommandRouter(
        catalog,
        {"help": operation, "about": operation},
        features,
        ai=ai,
        ai_input_routing=routing,
        addressed_input_hints=AddressedInputHintService(),
    )
    claimed = shape == "literal"
    assert router.recognizes(context)
    reply = await router.dispatch(context)
    assert reply is not None
    assert reply.message == OutboundMessage.from_text("command" if claimed else "chat")
    assert operation.await_count == int(claimed)
    assert ai.chat_reply.await_count == int(not claimed)
    if not claimed:
        assert ai.chat_reply.await_args.kwargs["prompt"] == text.strip()
    decision = routing.decide(context, CommandContext(actor, conversation))
    assert decision.try_chat is not claimed


def _normalized_contracts() -> tuple[CommandContract, ...]:
    config = MessageConfig.model_validate(
        {
            "commands": [
                {
                    "id": "example",
                    "commands": ["Hello World"],
                    "messages": ["reply"],
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
    if id_ == "messaging.example":
        config = MessageConfig.model_validate(
            {
                "commands": [
                    {
                        "id": "example",
                        "commands": [name],
                        "messages": ["reply"],
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
async def test_public_meeting_route_preserves_explicit_normalization() -> None:
    contract = meeting_command_contracts(("Meeting",))[0]
    catalog = CommandCatalog()
    catalog.load(
        (PluginContribution(id="meeting", commands=(contract,)),),
        known_features=("meeting",),
    )
    operation = AsyncMock(return_value=OutboundMessage.from_text("meeting"))
    router = PortableCommandRouter(
        catalog,
        {"meeting": operation},
        FEATURES,
        ai=Mock(),
        ai_input_routing=AiInputRoutingService(FEATURES, catalog),
        addressed_input_hints=AddressedInputHintService(),
    )
    for text in ("Meeting", " mEeTing ", "M E E T I N G", "/Meeting", "Meeting X"):
        event = private_message_event(text, user_id=100)
        context = message_input_context(event)
        claimed = contract.matches_direct_input(CONTEXT, text)
        assert router.recognizes(context) == claimed
        reply = await router.dispatch(context)
        assert (reply is not None) == claimed
