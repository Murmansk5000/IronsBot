from __future__ import annotations

from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.config.models.messaging import CommandCooldownConfig
from ironsbot.core.command_catalog import CommandCatalog
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.features import FEATURE_KEYS
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import SendResult
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.player_reference_commands import player_reference_input_matcher
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.services.ai.command_contracts import ai_chat_command_contracts
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.identity.player_accounts import (
    PlayerAccount,
    PlayerAccountRegistry,
)
from ironsbot.services.identity_link_store import CrossPlatformGroupLink
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.messaging.command_cooldown import CommandCooldownService
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_player_commands import build_portable_player_operations
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_rank_commands import build_portable_rank_operations
from ironsbot.services.portable_reply import deliver_portable_reply
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.player_query import (
    extract_player_binding_arg,
    extract_player_query_arg,
)
from ironsbot.services.seer.player_service import PlayerService
from ironsbot.services.seer.player_shortcut_contracts import (
    parse_player_shortcut_command,
)
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts
from ironsbot.services.seer.rank_list_parsing import parse_rank_player_target_command
from ironsbot.services.seer.rank_queries import RankQueryService
from tests.helpers.onebot_events import group_message_event, private_message_event
from tests.helpers.onebot_inputs import command_context, message_input_context
from tests.test_portable_player_commands import _PlayerService
from tests.test_portable_rank_commands import _RankQueryService

_ADMIN = ActorRef(Platform.ONEBOT, "100")
_REGULAR = ActorRef(Platform.ONEBOT, "200")
_GROUP = ConversationRef(Platform.ONEBOT, "group", "300")
_PLAYER_ID = 123456


def test_player_prefix_chat_is_not_claimed_with_member_mention() -> None:
    resolver = PlayerIdResolver(
        lambda reference, _conversation: (
            _PLAYER_ID if reference == "示例玩家" else None
        ),
        lambda _actor: None,
    )
    for text in ("米米号发了吗", "绑定米米号发了吗"):
        event = group_message_event(
            message=Message([MessageSegment.at(456), MessageSegment.text(f" {text}")]),
            group_id=int(_GROUP.id),
        )
        assert not any(
            command.matches_direct_input(command_context(event), text)
            for command in seer_command_contracts(resolver)
            if command.id in {"seer.player.bind", "seer.player.query"}
        )

    for text, current in (
        ("米米号示例玩家", resolver),
        (
            "米米号发了吗",
            PlayerIdResolver(
                lambda reference, _conversation: (
                    _PLAYER_ID if reference == "发了吗" else None
                ),
                lambda _actor: None,
            ),
        ),
    ):
        contract = next(
            command
            for command in seer_command_contracts(current)
            if command.id == "seer.player.query"
        )
        event = group_message_event(text, group_id=int(_GROUP.id))
        assert contract.matches_direct_input(command_context(event), text)


def _runtime(
    context: MessageInputContext, resolver: PlayerIdResolver, *, enabled: bool
) -> SimpleNamespace:
    granted = frozenset({"seer_player", "seer_rank"}) if enabled else frozenset()
    features = FeatureService(
        {context.message.conversation: granted},
        {context.message.actor: granted},
        frozenset(),
    )
    sessions = PortableQuerySessions()
    config = CommandCooldownConfig(enabled=True)
    requests = Mock(wraps=InFlightRequestService(features, config))
    cooldown = Mock(wraps=CommandCooldownService(config, features))
    sessions.interactions.request_service = requests
    sessions.interactions.cooldown = cooldown
    service = Mock(spec=PlayerService, wraps=_PlayerService())
    rank = Mock(spec=RankQueryService, wraps=_RankQueryService())
    operations = build_portable_player_operations(
        service, resolver, sessions, features, PlayerDetailExtensionRegistry()
    )
    operations.update(
        build_portable_rank_operations(
            rank, resolver, sessions, operations["seer.player.query"], features
        )
    )
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="seer_query",
                commands=tuple(
                    command
                    for command in seer_command_contracts(resolver)
                    if command.id in operations
                ),
            ),
            PluginContribution(
                id="rank_help",
                commands=tuple(
                    command
                    for command in rank_help_command_contracts(resolver)
                    if command.id in operations
                ),
            ),
        ),
        known_features=FEATURE_KEYS,
    )
    router = PortableCommandRouter(
        catalog,
        operations,
        features,
        ai=Mock(),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )
    return SimpleNamespace(
        router=router,
        catalog=catalog,
        features=features,
        requests=requests,
        cooldown=cooldown,
        service=service,
        rank=rank,
    )


def test_group_alias_is_visible_to_linked_official_group_only() -> None:
    principals = IdentityPrincipalService()
    registry = PlayerAccountRegistry(
        (PlayerAccount(_PLAYER_ID, "示例玩家", (), None),),
        private_alias_groups={_GROUP: ("示例玩家",)},
    )
    registry.bind_conversation_principals(principals.conversation_principal)
    official = ConversationRef(
        Platform.QQ_OFFICIAL, "group", "opaque-group", account_id="example-app"
    )
    assert registry.resolve_player_id("示例玩家", conversation=official) is None

    principals.register_group_link(
        CrossPlatformGroupLink("300", "example-app", "opaque-group", 1.0)
    )

    assert registry.resolve_player_id("示例玩家", conversation=official) == _PLAYER_ID
    assert (
        registry.resolve_player_id(
            "示例玩家",
            conversation=ConversationRef(
                Platform.QQ_OFFICIAL,
                "group",
                "another-group",
                account_id="example-app",
            ),
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prefix", ["米米号", "绑定米米号", "收集", "巅峰", "群星牌", "成就榜"]
)
@pytest.mark.parametrize("reference", ["123456", "示例玩家"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("platform", list(Platform))
async def test_public_player_route_matches_catalog_and_admits_once(
    prefix: str,
    reference: str,
    platform: Platform,
    *,
    enabled: bool,
) -> None:
    resolver = PlayerIdResolver(
        lambda value, _conversation: (
            _PLAYER_ID if value in {"123456", "示例玩家"} else None
        ),
        lambda _actor: None,
    )
    text = prefix + reference
    context = MessageInputContext(
        IncomingMessageRef(
            platform,
            ActorRef(platform, "123"),
            ConversationRef(platform, "group", "300"),
            "1",
            text,
        ),
        mentions_bot=True,
    )
    runtime = _runtime(context, resolver, enabled=enabled)
    from ironsbot.core.command_catalog import command_context_from_input

    claimed = runtime.catalog.claims_direct_input(
        command_context_from_input(context), runtime.features, text
    )
    assert claimed is enabled
    reply = await runtime.router.dispatch(context)
    assert (reply is not None) is enabled
    if reply is not None:
        from unittest.mock import AsyncMock

        await deliver_portable_reply(
            reply,
            AsyncMock(return_value=SendResult(delivered=True, message_id="receipt")),
        )
        runtime.cooldown.admit.assert_called_once()
        assert runtime.cooldown.admit.call_args.kwargs["actor"] == context.message.actor
        expected = {
            "米米号": runtime.service.query,
            "绑定米米号": runtime.service.bind_player,
            "收集": runtime.service.shortcut,
            "巅峰": runtime.service.shortcut,
            "群星牌": runtime.service.shortcut,
            "成就榜": runtime.rank.prepare_player,
        }[prefix]
        expected.assert_awaited_once()
    else:
        runtime.cooldown.admit.assert_not_called()
        runtime.service.query.assert_not_awaited()
        runtime.service.bind_player.assert_not_awaited()
        runtime.service.shortcut.assert_not_awaited()
        runtime.rank.prepare_player.assert_not_awaited()


@pytest.mark.parametrize(
    "prefix", ("米米号", "查询玩家信息", "收集", "巅峰", "群星牌", "绑定米米号")
)
@pytest.mark.parametrize(
    ("actor", "group", "reference", "expected"),
    (
        (_ADMIN, False, "私有示例", True),
        (_REGULAR, False, "私有示例", False),
        (_REGULAR, True, "私有示例", True),
        (_REGULAR, False, "公开示例", True),
        (_ADMIN, False, "不认识的玩家", False),
        (_ADMIN, False, "123456", True),
    ),
)
def test_player_command_ownership_matches_resolution(
    *, prefix: str, actor: ActorRef, group: bool, reference: str, expected: bool
) -> None:
    registry = PlayerAccountRegistry(
        (
            PlayerAccount(_PLAYER_ID, "私有示例", (), None),
            PlayerAccount(_PLAYER_ID + 1, "公开示例", (), None, public=True),
        ),
        private_alias_groups={_GROUP: ("私有示例",)},
    )
    features = FeatureService(
        group_features={_GROUP: frozenset({"seer_player", "ai_chat"})},
        actor_features={_REGULAR: frozenset({"seer_player", "ai_chat"})},
        superusers=frozenset({_ADMIN}),
    )
    binding = Mock(side_effect=AssertionError("ownership must not load bindings"))
    resolver = PlayerIdResolver(
        lambda reference, conversation: registry.resolve_player_id(
            reference, conversation=conversation
        ),
        binding,
        privileged_reference_lookup=lambda reference, conversation: (
            registry.resolve_player_id(
                reference, conversation=conversation, include_private=True
            )
        ),
        is_privileged_actor=features.is_actor_superuser,
    )
    commands = tuple(
        command
        for command in seer_command_contracts(resolver)
        if command.id.startswith("seer.player.")
    )
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(id="seer_query", commands=commands),
            PluginContribution(
                id="ai_chat",
                commands=ai_chat_command_contracts(enabled=True),
            ),
        ),
        known_features={"seer_player", "ai_chat"},
    )
    event_factory = (
        partial(group_message_event, group_id=int(_GROUP.id))
        if group
        else private_message_event
    )
    text = prefix + reference
    event = event_factory(text, user_id=int(actor.id))

    target = resolver.resolve(message_input_context(event), reference)
    assert (target.player_id is not None) is expected
    assert (
        catalog.claims_direct_input(command_context(event), features, text) is expected
    )
    if not group:
        # Exercise the actual AI routing rule, without invoking a completion API.
        assert (
            not AiInputRoutingService(features, catalog)
            .decide(message_input_context(event), command_context(event))
            .try_chat
        )
    binding.assert_not_called()


@pytest.mark.parametrize("prefix", ["米米号", "绑定米米号"])
@pytest.mark.parametrize("split_at", [1, 2])
def test_player_ownership_preserves_literal_command_prefix(
    prefix: str,
    split_at: int,
) -> None:
    text = prefix[:split_at] + " " + prefix[split_at:] + "123456"
    event = private_message_event(text)
    context = command_context(event)
    matcher = player_reference_input_matcher((prefix,), lambda *_: False)
    actual = (
        extract_player_binding_arg(text) is not None
        if prefix == "绑定米米号"
        else extract_player_query_arg(text) is not None
    )
    assert not actual
    assert matcher(text, context) is actual


@pytest.mark.parametrize(
    "prefix",
    ["绑定米米号", "米米号", "收集", "巅峰", "群星牌", "成就榜"],
)
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    "target",
    ["numeric", "alias", "member", "bot", "mixed", "multiple", "unbound", "reply"],
)
def test_public_player_contracts_preserve_member_targets_and_feature_policy(
    prefix: str,
    target: str,
    *,
    enabled: bool,
) -> None:
    resolver = PlayerIdResolver(
        lambda reference, _conversation: (
            _PLAYER_ID if reference in {str(_PLAYER_ID), "示例玩家"} else None
        ),
        lambda actor: _PLAYER_ID if actor.id == "456" else None,
    )
    message = Message(prefix)
    if target in {"numeric", "alias"}:
        message += str(_PLAYER_ID) if target == "numeric" else "示例玩家"
    else:
        message += MessageSegment.at(
            1 if target == "bot" else 789 if target == "unbound" else 456
        )
        if target == "mixed":
            message += "示例玩家"
        elif target == "multiple":
            message += MessageSegment.at(789)
    event = group_message_event(
        message=message,
        user_id=456 if target == "bot" else 123,
        group_id=int(_GROUP.id),
        reply_sender_user_id=456 if target == "reply" else None,
    )
    if event.reply is not None:
        event.reply.message = Message([MessageSegment.at(789)])
    context = message_input_context(event)
    runtime = _runtime(context, resolver, enabled=enabled)
    assert (
        runtime.catalog.claims_direct_input(
            command_context(event), runtime.features, context.text
        )
        is enabled
    )
    if not enabled or prefix in {"绑定米米号", "米米号"}:
        return
    if target == "bot" and prefix == "成就榜":
        # Mentioning the entry bot requests the list, not a member's rank.
        assert not context.member_mentions
        return
    parsed = (
        parse_rank_player_target_command(context.text)
        if prefix == "成就榜"
        else parse_player_shortcut_command(context.text)
    )
    assert parsed is not None
    resolved = resolver.resolve(
        context,
        parsed.player_reference,
        allow_default_binding=prefix != "成就榜",
    )
    player_id = resolved.player_id
    if target in {"mixed", "multiple", "unbound"}:
        assert player_id is None
        assert resolved.error
    else:
        assert player_id == _PLAYER_ID
        assert resolved.error is None
