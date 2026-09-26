from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.messaging import (
    MessageConfig,
    MessageKeywordReplyAction,
    MessageMentionReplyAction,
)
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
from ironsbot.services.messaging.service import MessagingService
from ironsbot.services.portable_commands import PortableCommandRouter

if TYPE_CHECKING:
    from ironsbot.core.messaging import AiIntentAction
    from ironsbot.services.ai.actions import AiIntentActionExecutor
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.portable_reply import PortableOperation

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


class _MentionReplies:
    def __init__(self, action: MessageMentionReplyAction | None) -> None:
        self.action = action
        self.calls: list[MessageInputContext] = []

    def match_mention_reply(
        self,
        context: MessageInputContext,
    ) -> MessageMentionReplyAction | None:
        self.calls.append(context)
        return self.action


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
            PluginContribution(
                id="example",
                commands=(
                    CommandContract(
                        id="example.query",
                        plugin_id="example",
                        section="查询",
                        examples=("查询",),
                        description="示例查询",
                        features_any=("example",),
                    ),
                ),
            ),
        ),
        known_features={"ai_chat", "ai_intent", "example"},
    )
    return catalog


def _features() -> FeatureService:
    enabled = frozenset({"ai_chat", "ai_intent", "example"})
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


def _router(
    ai: _Ai,
    *,
    operation: PortableOperation | None = None,
    mention_replies: _MentionReplies | None = None,
) -> PortableCommandRouter:
    catalog = _catalog()
    features = _features()
    return PortableCommandRouter(
        catalog,
        {"example.query": operation or _run_query},
        features,
        ai=cast("AiService", ai),
        ai_intent_actions=cast("AiIntentActionExecutor", _Executor()),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        messaging=cast("MessagingService | None", mention_replies),
    )


async def _run_query(
    text: str,
    context: MessageInputContext,
) -> str:
    del text, context
    return "查询结果"


async def _run_silent_query(
    text: str,
    context: MessageInputContext,
) -> None:
    del text, context


@pytest.mark.asyncio
async def test_official_unaddressed_keyword_reply_precedes_ai() -> None:
    ai = _Ai(action=ACTION)
    catalog = _catalog()
    features = _features()
    messaging = MessagingService(
        MessageConfig(
            keyword_replies=[
                MessageKeywordReplyAction(
                    id="example-keyword",
                    keywords=["示例触发词"],
                    messages=["固定回复"],
                    feature="example",
                )
            ]
        ),
        ActivityConfig(),
        cast("Any", object()),
        features,
        cast("Any", object()),
        cast("Any", object()),
    )
    router = PortableCommandRouter(
        catalog,
        {"example.query": _run_query},
        features,
        ai=cast("AiService", ai),
        ai_intent_actions=cast("AiIntentActionExecutor", _Executor()),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        messaging=messaging,
    )
    context = _context(GROUP, "这里有示例触发词")

    assert router.recognizes(context)
    reply = await router.dispatch(context)

    assert reply is not None
    assert reply.message.parts == (TextPart("固定回复"),)
    assert ai.intent_calls == []


@pytest.mark.parametrize("input_form", ["direct", "mentioned"])
@pytest.mark.asyncio
async def test_group_command_precedes_ai_with_or_without_bot_mention(
    input_form: str,
) -> None:
    ai = _Ai(action=ACTION)
    router = _router(ai)
    context = _context(GROUP, "查询", mentions_bot=input_form == "mentioned")

    assert router.recognizes(context)
    reply = await router.dispatch(context)

    assert reply is not None
    assert reply.message.parts == (TextPart("查询结果"),)
    assert ai.intent_calls == []
    assert ai.chat_calls == []


@pytest.mark.asyncio
async def test_claimed_entity_query_can_stay_silent_after_an_empty_lookup() -> None:
    ai = _Ai(action=ACTION)
    router = _router(ai, operation=_run_silent_query)
    context = _context(GROUP, "查询")

    assert router.recognizes(context)
    assert await router.dispatch(context) is None
    assert ai.intent_calls == []
    assert ai.chat_calls == []


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
async def test_unaddressed_full_group_message_does_not_run_ai_fallback() -> None:
    ai = _Ai(action=ACTION)
    router = _router(ai)
    context = MessageInputContext(
        IncomingMessageRef(
            Platform.QQ_OFFICIAL,
            ACTOR,
            GROUP,
            "message-1",
            "群里的普通聊天",
        ),
        mentions_bot=False,
        automatic_fallback_allowed=False,
    )

    assert not router.recognizes(context)
    assert await router.dispatch(context) is None
    assert ai.intent_calls == []
    assert ai.chat_calls == []


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


@pytest.mark.asyncio
async def test_configured_mention_reply_precedes_ai_chat() -> None:
    ai = _Ai(action=ACTION)
    mentions = _MentionReplies(
        MessageMentionReplyAction(
            id="example",
            users=["example"],
            messages=["第一条", "第二条"],
        )
    )
    router = _router(ai, mention_replies=mentions)
    context = _context(GROUP, "随便聊聊", mentions_bot=True)

    assert router.recognizes(context)
    reply = await router.dispatch(context)

    assert reply is not None
    assert reply.message.parts == (TextPart("第一条"),)
    assert reply.additional_messages[0].parts == (TextPart("第二条"),)
    assert ai.intent_calls == []
    assert ai.chat_calls == []


@pytest.mark.asyncio
async def test_explicit_command_precedes_configured_mention_reply() -> None:
    ai = _Ai(action=ACTION)
    mentions = _MentionReplies(
        MessageMentionReplyAction(
            id="example",
            users=["example"],
            messages=["mention reply"],
        )
    )
    router = _router(ai, mention_replies=mentions)

    reply = await router.dispatch(_context(GROUP, "查询", mentions_bot=True))

    assert reply is not None
    assert reply.message.parts == (TextPart("查询结果"),)
    assert mentions.calls == []
    assert ai.intent_calls == []
    assert ai.chat_calls == []
