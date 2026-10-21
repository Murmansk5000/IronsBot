from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.config.models.messaging import CommandCooldownConfig
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
from ironsbot.services.seer.data import DataUnavailableError


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize(
    "outcome",
    [
        "success",
        "business_failure",
        "delivery_failure",
        "exception",
        "cancelled",
        "unclaimed",
        "completion_failure",
    ],
)
async def test_shared_command_owns_admission_until_actual_completion(
    platform: Platform,
    outcome: str,
) -> None:
    context = MessageInputContext(
        IncomingMessageRef(
            platform,
            ActorRef(platform, "test-user"),
            ConversationRef(platform, "group", "test-group"),
            "test-message",
            "测试查询",
        ),
        mentions_bot=True,
    )
    features = FeatureService(
        {context.message.conversation: frozenset({"help"})},
        {},
        frozenset(),
    )
    catalog = CommandCatalog()
    contract = CommandContract(
        id="test.query",
        plugin_id="test",
        section="test",
        examples=("测试查询",),
        description="query",
        features_all=("help",),
        category=RequestCategory.OTHER_NETWORK,
    )
    catalog.load(
        (PluginContribution(id="test", commands=(contract,)),), known_features=("help",)
    )
    sessions = PortableQuerySessions()
    service = InFlightRequestService(features, CommandCooldownConfig())
    admission = Mock(wraps=service)
    sessions.interactions.request_service = admission
    finished = Mock(
        side_effect=RuntimeError("completion failed")
        if outcome == "completion_failure"
        else None
    )

    async def execute(text: str, context: MessageInputContext) -> PortableReply | None:
        del text, context
        if outcome == "exception":
            raise DataUnavailableError
        if outcome == "cancelled":
            raise asyncio.CancelledError
        if outcome == "unclaimed":
            return None
        return PortableReply(
            OutboundMessage.from_text(
                "result", request_succeeded=outcome != "business_failure"
            ),
            on_finished=finished,
        )

    router = PortableCommandRouter(
        catalog,
        {"test.query": execute},
        features,
        ai=cast("Any", None),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )
    if outcome == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await router.dispatch(context)
    else:
        reply = await router.dispatch(context)
        if outcome == "unclaimed":
            assert reply is None
        else:
            assert reply is not None
            send = AsyncMock(
                return_value=SendResult(
                    delivered=outcome != "delivery_failure",
                    message_id="test-receipt"
                    if outcome != "delivery_failure"
                    else None,
                    error_code="send_failed" if outcome == "delivery_failure" else None,
                )
            )
            if outcome == "completion_failure":
                with pytest.raises(RuntimeError, match="completion failed"):
                    await deliver_portable_reply(reply, send)
            else:
                await deliver_portable_reply(reply, send)
            assert reply.outcome.failed is (outcome != "success")
            if reply.on_finished is not None:
                reply.on_finished()
            assert finished.call_count <= 1
    assert admission.admit.call_count == 1
    if outcome == "success":
        admission.finish.assert_called_once()
    else:
        admission.finish.assert_not_called()
        admission.release.assert_called_once()
    request = direct_command_request(
        contract.id, context.text, context, category=contract.category
    )
    assert request is not None
    decision = service.admit(
        actor=context.message.actor,
        conversation=context.message.conversation,
        request=request,
        bot_id=context.request_bot_id,
    )
    assert decision.allowed is (outcome != "success")


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("shared", [False, True])
async def test_silent_menu_selection_preserves_menu_without_false_reply(
    platform: Platform,
    *,
    shared: bool,
) -> None:
    clock = [0.0]
    sessions = PortableQuerySessions(now=lambda: clock[0])
    context = MessageInputContext(
        IncomingMessageRef(
            platform,
            ActorRef(platform, "test-user"),
            ConversationRef(platform, "group", "test-group"),
            "test-message",
            "1",
        ),
        mentions_bot=True,
    )
    select = AsyncMock(return_value=None)
    message = sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=(1,),
            select=select,
            shared_select=select,
            shared_choice_indexes=frozenset({1}),
            prompt=OutboundMessage.from_text("choose"),
            keep_open=True,
            shareable=True,
        ),
    )
    sessions.record_delivery(
        context, message, SendResult(delivered=True, message_id="menu")
    )
    original = sessions.active_prompt(context)
    assert original is not None
    clock[0] = 30.0
    if shared:
        responder = replace(
            context,
            message=replace(
                context.message,
                actor=replace(context.message.actor, id="test-other"),
                reply_to_id="menu",
            ),
        )
        result = await sessions.select_shared("1", context, responder)
    else:
        result = await sessions.interactions.select("1", context)
    assert result is None
    select.assert_awaited_once()
    current = sessions.active_prompt(context)
    assert current is not None
    assert current.expires_at == original.expires_at
