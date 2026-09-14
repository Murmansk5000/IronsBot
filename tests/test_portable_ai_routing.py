from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.core.command_catalog import (
    CommandCatalog,
    CommandContract,
)
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.services.ai.command_contracts import ai_chat_command_contracts
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.portable_commands import PortableCommandRouter

if TYPE_CHECKING:
    from ironsbot.core.messaging import AiIntentAction
    from ironsbot.services.ai.actions import AiIntentActionExecutor
    from ironsbot.services.ai.service import AiService

ACTOR = ActorRef(Platform.QQ_OFFICIAL, "actor", account_id="app")
GROUP = ConversationRef(
    Platform.QQ_OFFICIAL,
    "group",
    "group",
    account_id="app",
)
PRIVATE = ConversationRef(
    Platform.QQ_OFFICIAL,
    "private",
    "actor",
    account_id="app",
)
ACTION = cast("AiIntentAction", object())


class _Ai:
    def __init__(self, *, action: AiIntentAction | None) -> None:
        self.action = action
        self.intent_calls: list[tuple[str, str | None]] = []
        self.chat_calls: list[str] = []

    async def classify_intent(
        self,
        text: str,
        **kwargs: object,
    ) -> AiIntentAction | None:
        self.intent_calls.append((text, cast("str | None", kwargs["source_context"])))
        return self.action

    async def chat_reply(self, *, prompt: str, **_kwargs: object) -> str:
        self.chat_calls.append(prompt)
        return "聊天回复"


class _Executor:
    async def execute(
        self,
        action: AiIntentAction,
        text: str,
        **_kwargs: object,
    ) -> tuple[OutboundMessage, ...]:
        assert action is ACTION
        assert text == "加入战队"
        return (
            OutboundMessage.from_text("第一条"),
            OutboundMessage.from_text("第二条"),
        )


def _catalog() -> CommandCatalog:
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="ai_chat",
                commands=ai_chat_command_contracts(enabled=True),
            ),
            PluginContribution(
                id="ai_intent",
                commands=(
                    CommandContract(
                        id="ai_intent.team",
                        plugin_id="ai_intent",
                        section="AI",
                        examples=("加入战队",),
                        description="加入战队意图",
                        features_any=("ai_intent",),
                        interaction="automatic",
                    ),
                ),
            ),
        ),
        known_features={"ai_chat", "ai_intent"},
    )
    return catalog


def _features() -> FeatureService:
    enabled = frozenset({"ai_chat", "ai_intent"})
    return FeatureService(
        {GROUP: enabled},
        {ACTOR: enabled},
        frozenset(),
        superuser_bypass=False,
    )


def _context(
    conversation: ConversationRef,
    text: str,
    *,
    mentions_bot: bool = False,
) -> MessageInputContext:
    return MessageInputContext(
        IncomingMessageRef(
            Platform.QQ_OFFICIAL,
            ACTOR,
            conversation,
            "message-1",
            text,
        ),
        mentions_bot=mentions_bot,
    )


def _router(ai: _Ai) -> PortableCommandRouter:
    catalog = _catalog()
    features = _features()
    return PortableCommandRouter(
        catalog,
        {},
        features,
        ai=cast("AiService", ai),
        ai_intent_actions=cast("AiIntentActionExecutor", _Executor()),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
    )


@pytest.mark.asyncio
async def test_group_direct_intent_returns_every_action_message() -> None:
    ai = _Ai(action=ACTION)
    router = _router(ai)
    context = _context(GROUP, "加入战队")

    assert router.recognizes(context)
    reply = await router.dispatch(context)

    assert reply is not None
    assert reply.message.parts == (TextPart("第一条"),)
    assert reply.additional_messages[0].parts == (TextPart("第二条"),)
    assert ai.chat_calls == []
    source_context = ai.intent_calls[0][1]
    assert source_context is not None
    assert "平台：qq_official" in source_context


@pytest.mark.asyncio
async def test_private_input_falls_back_to_chat_after_unmatched_intent() -> None:
    ai = _Ai(action=None)
    router = _router(ai)

    reply = await router.dispatch(_context(PRIVATE, "随便聊聊"))

    assert reply is not None
    assert reply.message.parts == (TextPart("聊天回复"),)
    assert ai.chat_calls == ["随便聊聊"]


@pytest.mark.asyncio
async def test_group_bot_mention_skips_intent_and_uses_chat() -> None:
    ai = _Ai(action=ACTION)
    router = _router(ai)

    reply = await router.dispatch(_context(GROUP, "随便聊聊", mentions_bot=True))

    assert reply is not None
    assert reply.message.parts == (TextPart("聊天回复"),)
    assert ai.intent_calls == []
