from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Literal, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.action_categories import RequestCategory
from ironsbot.core.command_catalog import CommandCatalog, CommandContract
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
from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.operations.request_feedback import send_request_feedback
from ironsbot.services.player_extension_commands import build_player_extension_operation
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_player_commands import build_portable_player_operations
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
    PortableTextInputSpec,
)
from ironsbot.services.portable_reply import PortableReply, deliver_portable_reply
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionAction,
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.query_result import QueryReply
from tests.helpers.command_execution import operation_router
from tests.helpers.onebot_events import group_message_event
from tests.helpers.onebot_inputs import message_input_context

if TYPE_CHECKING:
    from ironsbot.services.seer.player_service import PlayerService


@pytest.mark.asyncio
async def test_shared_ingress_finishes_silently_for_empty_query_result() -> None:
    sessions = PortableQuerySessions()
    sent = AsyncMock()

    async def operation(
        text: str,
        context: MessageInputContext,
    ) -> None:
        del text, context

    context = message_input_context(group_message_event("刻印"))
    router = operation_router(operation, context, sessions)
    await router.ingress.handle(context, sent)

    sent.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("interaction", ["none", "menu", "text"])
@pytest.mark.parametrize("delivered", [False, True])
async def test_initial_reply_uses_the_same_delivery_contract_with_or_without_menu(
    *,
    interaction: Literal["none", "menu", "text"],
    delivered: bool,
) -> None:
    sessions = PortableQuerySessions()
    sent = AsyncMock(
        return_value=SendResult(
            delivered=delivered,
            message_id="sent-1" if delivered else None,
            error_code=None if delivered else "rejected",
        )
    )
    success, failure = Mock(), Mock()
    follow_up = AsyncMock(return_value=OutboundMessage.from_text("finished"))

    async def choose(_choice: str, _context: MessageInputContext) -> OutboundMessage:
        return OutboundMessage.from_text("selected")

    async def operation(text: str, context: MessageInputContext) -> PortableReply:
        del text
        message = OutboundMessage.from_text("choose")
        if interaction == "menu":
            message = sessions.offer_menu(
                context,
                PortableMenuSpec(choices=("one",), select=choose, prompt=message),
            )
        elif interaction == "text":
            message = sessions.offer_text_input(
                context,
                PortableTextInputSpec(submit=choose, prompt=message),
            )
        return PortableReply(
            message,
            additional_messages=(OutboundMessage.from_text("extra"),),
            on_delivered=success,
            on_delivery_failed=failure,
            follow_up=follow_up,
        )

    context = message_input_context(group_message_event("query"))
    router = operation_router(operation, context, sessions)
    await router.ingress.handle(context, sent)

    if delivered:
        success.assert_called_once_with()
        failure.assert_not_called()
        follow_up.assert_awaited_once_with()
        assert [call.args[0].parts for call in sent.await_args_list] == [
            OutboundMessage.from_text(text).parts
            for text in ("choose", "extra", "finished")
        ]
    else:
        failure.assert_called_once_with()
        success.assert_not_called()
        follow_up.assert_not_awaited()
        sent.assert_awaited_once()
    assert sessions.has_active_session(context) == (interaction != "none" and delivered)
    if interaction == "menu" and delivered:
        assert sessions.menu_anchor(context) == "sent-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "blocked"),
    [
        ("收集", False),
        ("巅峰", False),
        ("群星牌", False),
        ("档案", False),
        ("档案", True),
    ],
)
@pytest.mark.parametrize("platform", list(Platform))
async def test_public_player_shortcut_runs_shared_progress_and_delivery(
    text: str,
    platform: Platform,
    *,
    blocked: bool,
) -> None:
    async def query(*_args: object, **_kwargs: object) -> QueryReply:
        await send_request_feedback(queued=False)
        return QueryReply(text="result", image=b"image-bytes")

    service = SimpleNamespace(shortcut=AsyncMock(side_effect=query))
    extensions = PlayerDetailExtensionRegistry()
    extensions.register(
        PlayerDetailExtensionAction(
            id="sample_detail",
            feature="seer_player",
            label="档案",
            aliases=("档案",),
            command_help_id="sample.detail",
            query=service.shortcut,
            action=ActionDefinition(
                "sample_detail", "档案", category=RequestCategory.OTHER_NETWORK
            ),
        )
    )
    context = MessageInputContext(
        IncomingMessageRef(
            platform,
            ActorRef(platform, "caller"),
            ConversationRef(platform, "group", "group"),
            "1",
            text,
        ),
        mentions_bot=False,
    )
    features = FeatureService(
        {
            context.message.conversation: frozenset(
                {"blacklist"} if blocked else {"seer_player"}
            )
        },
        {},
        frozenset(),
    )
    sessions = PortableQuerySessions()
    resolver = PlayerIdResolver(lambda *_: None, lambda _: 700001)
    operations = {
        "seer.player.default": build_portable_player_operations(
            cast("PlayerService", service), resolver, sessions, features, extensions
        )["seer.player.default"],
        "sample.detail": build_player_extension_operation(
            extensions, resolver, features, sessions
        ),
    }
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="seer_query",
                commands=tuple(
                    command
                    for command in seer_command_contracts(resolver)
                    if command.id == "seer.player.default"
                ),
            ),
            PluginContribution(
                id="example",
                commands=(
                    CommandContract(
                        id="sample.detail",
                        plugin_id="example",
                        section="详情",
                        examples=("档案",),
                        description="示例详情",
                        features_all=("seer_player",),
                        category=RequestCategory.OTHER_NETWORK,
                    ),
                ),
            ),
        ),
        known_features=("seer_player",),
    )
    router = PortableCommandRouter(
        catalog,
        operations,
        features,
        ai=Mock(),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
        resolved_target_commands=frozenset({"sample.detail"}),
    )
    send = AsyncMock(return_value=SendResult(delivered=True, message_id="sent-1"))
    reply = await router.dispatch(context)
    if blocked:
        assert reply is None
        service.shortcut.assert_not_awaited()
        send.assert_not_awaited()
        return
    assert reply is not None
    await deliver_portable_reply(reply, send)
    service.shortcut.assert_awaited_once()
    expected_sends = ("progress", "result")
    assert send.await_count == len(expected_sends)
    assert send.await_args is not None
    assert (
        send.await_args.args[0]
        == QueryReply(
            text="result",
            image=b"image-bytes",
        ).to_outbound()
    )
