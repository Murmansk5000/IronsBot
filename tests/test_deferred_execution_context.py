from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from ironsbot.config.models.messaging import CommandCooldownConfig
from ironsbot.core.action_categories import RequestCategory
from ironsbot.core.command_catalog import CommandCatalog, CommandContract
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.message_origin import current_message_origin, message_origin
from ironsbot.core.outbound import OutboundMessage, SendResult
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
    current_semantic_request_trace,
    semantic_request_scope,
)
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
)
from ironsbot.services.portable_reply import PortableReply, deliver_portable_reply
from ironsbot.services.portable_request_identity import direct_command_request

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable


def _runtime(
    context: MessageInputContext,
    request: SemanticRequest,
    mode: str,
    check: Callable[[str], None],
) -> tuple[PortableCommandRouter, Mock]:
    features = FeatureService({}, {}, frozenset())
    sessions = PortableQuerySessions()
    requests = Mock(wraps=InFlightRequestService(features, CommandCooldownConfig()))
    sessions.interactions.request_service = requests
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="test",
                commands=(
                    CommandContract(
                        id="test.query",
                        plugin_id="test",
                        section="test",
                        examples=("测试查询",),
                        description="test",
                        category=RequestCategory.LOCAL,
                    ),
                ),
            ),
        ),
        known_features=(),
    )

    async def work() -> OutboundMessage:
        check("work")
        await asyncio.sleep(0)
        check("resumed")

        async def result() -> PortableReply:
            return PortableReply(OutboundMessage.from_text("result"))

        # The deferred operation is already admitted; it must not reserve twice.
        nested = await sessions.interactions.execute_request(request, context, result)
        assert nested is not None
        return nested.message

    async def stream() -> AsyncGenerator[OutboundMessage, None]:
        yield await work()
        check("stream_resumed")

    async def continuation() -> PortableReply:
        message = await work()
        return PortableReply(
            message,
            follow_up=work if mode == "nested" else None,
            on_finished=lambda: check("child_finished"),
        )

    async def execute(text: str, context: MessageInputContext) -> PortableReply:
        del text, context
        check("execute")
        return PortableReply(
            OutboundMessage.from_text("initial"),
            follow_up=work if mode == "follow_up" else None,
            continuation=continuation if mode in {"continuation", "nested"} else None,
            additional_stream=stream if mode == "stream" else None,
            on_delivered=lambda: check("delivered"),
            on_finished=lambda: check("finished"),
        )

    router = PortableCommandRouter(
        catalog,
        {"test.query": execute},
        features,
        ai=Mock(),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )
    return router, requests


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("mode", ["follow_up", "continuation", "stream", "nested"])
@pytest.mark.parametrize("outcome", ["success", "cancelled", "transport_failure"])
async def test_deferred_business_and_receipts_restore_their_own_execution_context(
    platform: Platform, mode: str, outcome: str
) -> None:
    context = MessageInputContext(
        IncomingMessageRef(
            platform,
            ActorRef(platform, "caller"),
            ConversationRef(platform, "group", "group"),
            "message",
            "测试查询",
        ),
        mentions_bot=True,
    )
    request = direct_command_request(
        "test.query", context.text, context, category=RequestCategory.LOCAL
    )
    assert request is not None
    phases: list[str] = []

    def check(phase: str) -> None:
        assert current_message_origin() is context
        trace = current_semantic_request_trace()
        assert trace is not None and trace.request == request
        assert trace.actor == context.message.actor
        phases.append(phase)

    router, requests = _runtime(context, request, mode, check)
    reply = await router.dispatch(context)
    assert reply is not None
    assert current_message_origin() is None
    assert current_semantic_request_trace() is None
    foreign = replace(
        context, message=replace(context.message, message_id="foreign", text="other")
    )
    foreign_request = direct_command_request(
        "test.query", "other", foreign, category=RequestCategory.LOCAL
    )

    sent = 0

    async def send(_message: OutboundMessage) -> SendResult:
        nonlocal sent
        check("send")
        sent += 1
        if sent > 1:
            if outcome == "cancelled":
                raise asyncio.CancelledError
            if outcome == "transport_failure":
                raise RuntimeError
        return SendResult(delivered=True, message_id="receipt")

    with (
        message_origin(foreign),
        semantic_request_scope(foreign_request, actor=foreign.message.actor),
    ):
        if outcome == "success":
            assert await deliver_portable_reply(reply, send)
        else:
            with pytest.raises(
                asyncio.CancelledError if outcome == "cancelled" else RuntimeError
            ):
                await deliver_portable_reply(reply, send)
        assert current_message_origin() is foreign
        trace = current_semantic_request_trace()
        assert trace is not None and trace.request == foreign_request
    assert current_message_origin() is None
    assert current_semantic_request_trace() is None
    assert "work" in phases and phases[-1] == "finished"
    requests.admit.assert_called_once()
    if outcome == "success":
        requests.finish.assert_called_once()
        requests.release.assert_not_called()
    else:
        requests.finish.assert_not_called()
        requests.release.assert_called_once()


@pytest.mark.asyncio
async def test_unbound_reply_clears_unrelated_context_for_receipts_and_callbacks() -> (
    None
):
    def check() -> None:
        assert current_message_origin() is None
        assert current_semantic_request_trace() is None

    reply = PortableReply(
        OutboundMessage.from_text("unbound"),
        on_delivered=check,
        on_delivery_failed=check,
        on_finished=check,
    )
    context = MessageInputContext(
        IncomingMessageRef(
            Platform.ONEBOT,
            ActorRef(Platform.ONEBOT, "other"),
            ConversationRef(Platform.ONEBOT, "private", "other"),
            "other-message",
            "other",
        ),
        mentions_bot=False,
    )
    request = direct_command_request(
        "test.query", "other", context, category=RequestCategory.LOCAL
    )

    async def send(_message: OutboundMessage) -> SendResult:
        check()
        return SendResult(delivered=True, message_id="receipt")

    with (
        message_origin(context),
        semantic_request_scope(request, actor=context.message.actor),
    ):
        assert await deliver_portable_reply(reply, send)
        reply.delivered()
        reply.delivery_failed()
        reply.finished()
        assert current_message_origin() is context
        trace = current_semantic_request_trace()
        assert trace is not None and trace.request == request
    check()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_concurrent_deferred_replies_keep_distinct_actor_scopes(
    platform: Platform,
) -> None:
    async def run(index: int) -> None:
        context = MessageInputContext(
            IncomingMessageRef(
                platform,
                ActorRef(platform, f"caller-{index}"),
                ConversationRef(platform, "group", f"group-{index}"),
                str(index),
                "测试查询",
            ),
            mentions_bot=True,
        )
        request = direct_command_request(
            "test.query", context.text, context, category=RequestCategory.LOCAL
        )
        assert request is not None

        def check(_phase: str) -> None:
            assert current_message_origin() is context
            trace = current_semantic_request_trace()
            assert trace is not None and trace.actor == context.message.actor
            assert trace.request == request

        router, requests = _runtime(context, request, "nested", check)
        reply = await router.dispatch(context)
        assert reply is not None

        async def send(_message: OutboundMessage) -> SendResult:
            check("send")
            await asyncio.sleep(0)
            check("resumed send")
            return SendResult(delivered=True, message_id=str(index))

        assert await deliver_portable_reply(reply, send)
        assert current_message_origin() is None
        assert current_semantic_request_trace() is None
        requests.admit.assert_called_once()

    await asyncio.gather(run(1), run(2))


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_selection_outbound_retains_the_resolved_request_after_scope_exit(
    platform: Platform,
) -> None:
    owner = MessageInputContext(
        IncomingMessageRef(
            platform,
            ActorRef(platform, "caller"),
            ConversationRef(platform, "group", "group"),
            "menu-message",
            "menu",
        ),
        mentions_bot=False,
    )
    selection = replace(
        owner, message=replace(owner.message, message_id="selection-message", text="1")
    )
    sessions = PortableQuerySessions()
    request = SemanticRequest(
        ActionDefinition("test.selection", "selection", category=RequestCategory.LOCAL),
        SemanticTarget("resolved-player", "player"),
        SemanticRequestSource.MENU,
    )

    async def choose(_value: str, _context: MessageInputContext) -> OutboundMessage:
        return OutboundMessage.from_text("result")

    sessions.offer_menu(
        owner,
        PortableMenuSpec(
            choices=("player",),
            select=choose,
            prompt=OutboundMessage.from_text("menu"),
            semantic_request=lambda _value, _context: request,
        ),
    )
    with message_origin(selection):
        reply = await sessions.interactions.select("1", selection)
    assert reply is not None
    assert current_semantic_request_trace() is None

    async def send(_message: OutboundMessage) -> SendResult:
        assert current_message_origin() is selection
        trace = current_semantic_request_trace()
        assert trace is not None and trace.request == request
        assert trace.actor == selection.message.actor
        return SendResult(delivered=True, message_id="receipt")

    assert await deliver_portable_reply(reply, send)
    assert current_message_origin() is None
    assert current_semantic_request_trace() is None
