from __future__ import annotations

from ironsbot.core.command_catalog import (
    CommandCatalog,
    CommandContext,
    CommandContract,
)
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.services.ai.command_contracts import ai_chat_command_contracts
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.team.resource_commands import team_resource_command_contracts

ACTOR = ActorRef(Platform.ONEBOT, "100")
GROUP = ConversationRef(Platform.ONEBOT, "group", "200")
PRIVATE = ConversationRef(Platform.ONEBOT, "private", "100")


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
                        id="ai_intent.example",
                        plugin_id="ai_intent",
                        section="AI",
                        examples=("推荐一下",),
                        description="示例意图",
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
        known_features={"ai_chat", "ai_intent", "example", "blacklist"},
    )
    return catalog


def _features(*, blocked: bool = False) -> FeatureService:
    enabled = frozenset({"ai_chat", "ai_intent", "example"})
    return FeatureService(
        {GROUP: enabled},
        {ACTOR: enabled | ({"blacklist"} if blocked else set())},
        frozenset(),
        superuser_bypass=False,
    )


def _input(
    conversation: ConversationRef,
    text: str,
    *,
    mentions_bot: bool = False,
    reply_to_id: str | None = None,
    member_mentions: tuple[ActorRef, ...] = (),
) -> MessageInputContext:
    return MessageInputContext(
        IncomingMessageRef(
            Platform.ONEBOT,
            ACTOR,
            conversation,
            "message-1",
            text,
            direct_mentions=member_mentions,
            reply_to_id=reply_to_id,
        ),
        mentions_bot=mentions_bot,
    )


def _decide(context: MessageInputContext, *, blocked: bool = False):
    return AiInputRoutingService(_features(blocked=blocked), _catalog()).decide(
        context,
        CommandContext(
            context.message.actor,
            context.message.conversation,
            member_mentions=context.member_mentions,
        ),
    )


def test_group_direct_input_only_tries_intent() -> None:
    decision = _decide(_input(GROUP, "推荐一下"))

    assert decision.try_intent
    assert not decision.try_chat
    assert not decision.offer_help_hint


def test_group_bot_mention_only_tries_chat() -> None:
    decision = _decide(_input(GROUP, "聊聊", mentions_bot=True))

    assert not decision.try_intent
    assert decision.try_chat
    assert not decision.offer_help_hint


def test_empty_group_bot_mention_offers_help_even_when_chat_is_enabled() -> None:
    decision = _decide(_input(GROUP, "", mentions_bot=True))

    assert not decision.try_intent
    assert not decision.try_chat
    assert decision.offer_help_hint


def test_private_direct_input_tries_intent_then_chat() -> None:
    decision = _decide(_input(PRIVATE, "聊聊"))

    assert decision.try_intent
    assert decision.try_chat


def test_claimed_command_never_enters_ai() -> None:
    assert not _decide(_input(GROUP, "查询")).recognized
    assert not _decide(_input(GROUP, "查询", mentions_bot=True)).recognized
    assert not _decide(_input(PRIVATE, "查询")).recognized


def test_known_team_command_never_enters_ai_when_feature_is_unavailable() -> None:
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="ai_chat",
                commands=ai_chat_command_contracts(enabled=True),
            ),
            PluginContribution(
                id="team_resource",
                commands=team_resource_command_contracts(
                    enabled=True,
                    query_commands=("战队",),
                ),
            ),
        ),
        known_features={"ai_chat", "team_resource_subscription"},
    )
    features = FeatureService(
        {GROUP: frozenset({"ai_chat"})},
        {},
        frozenset(),
        superuser_bypass=False,
    )
    context = _input(GROUP, "战队订阅", mentions_bot=True)

    decision = AiInputRoutingService(features, catalog).decide(
        context,
        CommandContext(ACTOR, GROUP),
    )

    assert not decision.recognized


def test_reply_member_mention_and_blacklist_never_enter_ai() -> None:
    assert not _decide(_input(GROUP, "聊聊", reply_to_id="quoted")).recognized
    assert not _decide(
        _input(GROUP, "聊聊", member_mentions=(ActorRef(Platform.ONEBOT, "300"),))
    ).recognized
    assert not _decide(_input(PRIVATE, "聊聊"), blocked=True).recognized


def test_unavailable_group_chat_offers_help_hint() -> None:
    features = FeatureService({}, {}, frozenset(), superuser_bypass=False)
    context = _input(GROUP, "不会处理", mentions_bot=True)
    decision = AiInputRoutingService(features, _catalog()).decide(
        context,
        CommandContext(ACTOR, GROUP),
    )

    assert not decision.try_chat
    assert decision.offer_help_hint
