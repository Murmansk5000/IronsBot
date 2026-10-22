from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ironsbot.config.models.transport import SelfCommandsConfig
from ironsbot.core.outbound import (
    MentionPart,
    OutboundMessage,
    ReplyContext,
    TextPart,
)
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot.errors import OneBotTransportError
from ironsbot.integrations.onebot.http_api import (
    OneBotHttpApi,
    OneBotHttpRequest,
    OneBotHttpResponse,
)
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from ironsbot.integrations.onebot.transport import OneBotHttpConnection
from ironsbot.services.own_commands import OwnAccountCommandPolicy
from tests.helpers.onebot_events import own_account_input, self_command_event
from tests.helpers.runtime import build_test_runtime


@pytest.fixture
def echo_transport() -> SimpleNamespace:
    state = SimpleNamespace(
        error=None,
        response={"message_id": 1},
        block=False,
        entered=asyncio.Event(),
        release=asyncio.Event(),
        now=100.0,
    )

    async def api(request: OneBotHttpRequest) -> OneBotHttpResponse:
        name = request.url.rsplit("/", 1)[-1]
        if name == "get_login_info":
            return OneBotHttpResponse(
                200, '{"status":"ok","retcode":0,"data":{"nickname":"test"}}'
            )
        state.entered.set()
        if state.block:
            await state.release.wait()
        if state.error is not None:
            raise state.error
        return OneBotHttpResponse(
            200, json.dumps({"status": "ok", "retcode": 0, "data": state.response})
        )

    policy = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=True, prefixes=["demo "]), clock=lambda: state.now
    )
    bot = OneBotHttpConnection(
        "1",
        OneBotHttpApi(
            api_roots={"1": "http://test/"},
            access_token=None,
            timeout=1,
            request=api,
        ),
    )
    limits = build_test_runtime().outbound
    messenger = OneBotOutboundMessenger(
        Mock(for_conversation=Mock(return_value=bot)), limits, self_commands=policy
    )
    return SimpleNamespace(
        policy=policy, messenger=messenger, state=state, limits=limits, bot=bot
    )


@pytest.mark.asyncio
async def test_definitely_offline_send_does_not_block_later_manual_own_command(
    echo_transport: SimpleNamespace,
) -> None:
    echo_transport.state.error = OneBotTransportError(definitely_not_sent=True)
    result = await echo_transport.messenger.send(
        ConversationRef(Platform.ONEBOT, "group", "456"),
        OutboundMessage.from_text("demo help"),
    )
    assert not result.delivered
    assert (
        echo_transport.policy.accept(own_account_input(self_command_event("demo help")))
        is not None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["success", "missing_receipt", "timeout", "cancelled"]
)
async def test_echo_is_blocked_before_receipt_and_retained_when_delivery_is_possible(
    echo_transport: SimpleNamespace, outcome: str
) -> None:
    echo_transport.state.block = True
    if outcome == "missing_receipt":
        echo_transport.state.response = {}
    if outcome == "timeout":
        echo_transport.state.error = TimeoutError()
    candidate = own_account_input(self_command_event("demo help"))
    sending = asyncio.create_task(
        echo_transport.messenger.send(
            ConversationRef(Platform.ONEBOT, "group", "456"),
            OutboundMessage.from_text("demo help"),
        )
    )
    try:
        await asyncio.wait_for(echo_transport.state.entered.wait(), timeout=1)
        assert echo_transport.policy.accept(candidate) is None
        if outcome == "cancelled":
            sending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await sending
        else:
            echo_transport.state.release.set()
            result = await sending
            assert result.delivered is (outcome == "success")
        assert echo_transport.policy.accept(candidate) is None
        echo_transport.state.now = 700.0
        assert echo_transport.policy.accept(candidate) is not None
    finally:
        echo_transport.state.release.set()
        await asyncio.gather(sending, return_exceptions=True)


@pytest.mark.asyncio
async def test_admin_binding_echo_is_protected_without_prefix_commands(
    echo_transport: SimpleNamespace,
) -> None:
    echo_transport.policy.config.enabled = False
    actor = ActorRef(Platform.ONEBOT, "42")
    message = OutboundMessage((TextPart("绑定米米号123456"), MentionPart(actor)))
    result = await echo_transport.messenger.send(
        ConversationRef(Platform.ONEBOT, "group", "456"), message
    )
    assert result.delivered
    event = self_command_event("绑定米米号123456")
    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    event.original_message = Message("绑定米米号123456") + MessageSegment.at(42)
    assert echo_transport.policy.accept(own_account_input(event)) is None


@pytest.mark.asyncio
async def test_private_and_disabled_sends_do_not_create_group_echo_records(
    echo_transport: SimpleNamespace,
) -> None:
    result = await echo_transport.messenger.send(
        ConversationRef(Platform.ONEBOT, "private", "101"),
        OutboundMessage.from_text("demo help"),
    )
    assert result.delivered
    candidate = own_account_input(self_command_event("demo help"))
    assert echo_transport.policy.accept(candidate) is not None
    disabled = OneBotOutboundMessenger(
        Mock(),
        echo_transport.limits,
        enabled=False,
        self_commands=echo_transport.policy,
    )
    result = await disabled.send(
        ConversationRef(Platform.ONEBOT, "group", "456"),
        OutboundMessage.from_text("demo help"),
    )
    assert not result.attempted
    assert echo_transport.policy.accept(candidate) is not None


@pytest.mark.asyncio
async def test_rate_rejection_before_submission_does_not_register_echo(
    echo_transport: SimpleNamespace,
) -> None:
    from ironsbot.config.models.messaging import (
        OutboundRateLimitConfig,
        OutboundRateLimitWindowConfig,
    )

    echo_transport.limits.config = OutboundRateLimitConfig(
        enabled=True,
        windows=[OutboundRateLimitWindowConfig(window_seconds=60, max_messages=1)],
    )
    assert echo_transport.limits.acquire_reply(456).allowed
    result = await echo_transport.messenger.reply(
        ReplyContext(ConversationRef(Platform.ONEBOT, "group", "456"), "source"),
        OutboundMessage.from_text("demo help"),
    )
    assert not result.attempted
    assert not echo_transport.state.entered.is_set()
    assert (
        echo_transport.policy.accept(own_account_input(self_command_event("demo help")))
        is not None
    )
