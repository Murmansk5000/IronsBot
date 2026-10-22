from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import nonebot
import pytest

from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.config.models.messaging import (
    OutboundRateLimitConfig,
    OutboundRateLimitWindowConfig,
)
from ironsbot.core.outbound import DeliveryFailureKind, OutboundMessage, ReplyContext
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.onebot.connections import OneBotConnections
from ironsbot.integrations.onebot.errors import OneBotActionError
from ironsbot.integrations.onebot.http_api import OneBotHttpRequest, OneBotHttpResponse
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from ironsbot.integrations.onebot.transport import OneBotHttpConnection, OneBotTransport
from tests.helpers.runtime import build_test_runtime


@pytest.fixture
def transport() -> SimpleNamespace:
    try:
        driver = nonebot.get_driver()
    except ValueError:
        nonebot.init(_env_file=None)
        driver = nonebot.get_driver()
    state = SimpleNamespace(
        error=None,
        block=False,
        entered=asyncio.Event(),
        release=asyncio.Event(),
        calls=[],
    )

    async def api(
        request: OneBotHttpRequest,
    ) -> OneBotHttpResponse:
        name = request.url.rsplit("/", 1)[-1]
        data = json.loads(request.body)
        if name == "get_login_info":
            return OneBotHttpResponse(
                200, '{"status":"ok","retcode":0,"data":{"nickname":"test"}}'
            )
        state.calls.append(data)
        state.entered.set()
        if state.block:
            await state.release.wait()
        if state.error is not None:
            if isinstance(state.error, OneBotActionError):
                return OneBotHttpResponse(
                    200,
                    json.dumps(
                        {
                            "status": "failed",
                            "retcode": state.error.retcode,
                            "wording": "private-detail",
                        }
                    ),
                )
            raise state.error
        return OneBotHttpResponse(
            200, '{"status":"ok","retcode":0,"data":{"message_id":123}}'
        )

    runtime = build_test_runtime(
        outbound_config=OutboundRateLimitConfig(
            enabled=True,
            windows=[OutboundRateLimitWindowConfig(window_seconds=60, max_messages=1)],
            cooldown_message="limit reached",
        )
    )
    owner = TaskOwner()
    adapter = OneBotTransport(
        driver,
        spawn=owner.create,
        received=AsyncMock(),
        notices=AsyncMock(),
        request_http=api,
        connections=OneBotConnections(),
        observer=ApplicationLifecycle(task_owner=owner),
    )
    adapter.http_api.api_roots["1"] = "http://test/"
    bot = OneBotHttpConnection("1", adapter.http_api)
    messenger = OneBotOutboundMessenger(
        cast("Any", Mock(for_conversation=Mock(return_value=bot))), runtime.outbound
    )
    state.messenger = messenger
    state.service = runtime.outbound
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("proactive", [False, True])
@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("private-detail"),
        OneBotActionError(1200),
    ],
)
async def test_http_failures_use_shared_uncertain_settlement(
    transport: SimpleNamespace, error: Exception, *, proactive: bool
) -> None:
    transport.error = error
    conversation = ConversationRef(Platform.ONEBOT, "group", "100")
    message = OutboundMessage.from_text("result")
    result = (
        await transport.messenger.send(conversation, message)
        if proactive
        else await transport.messenger.reply(ReplyContext(conversation, "1"), message)
    )
    assert result.failure_kind is DeliveryFailureKind.UNCERTAIN
    assert "private-detail" not in (result.error_message or "")
    assert not transport.service.acquire_reply(100).allowed
    assert len(transport.calls) == 1
    assert str(transport.calls[0]["message"]).count("limit reached") == 1


@pytest.mark.asyncio
async def test_http_cancellation_after_submit_preserves_capacity(
    transport: SimpleNamespace,
) -> None:
    transport.block = True
    task = asyncio.create_task(
        transport.messenger.send(
            ConversationRef(Platform.ONEBOT, "group", "100"),
            OutboundMessage.from_text("result"),
        )
    )
    await transport.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not transport.service.acquire_reply(100).allowed
    assert len(transport.calls) == 1
