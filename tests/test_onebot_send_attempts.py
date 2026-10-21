from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import ActionFailed, Adapter, Bot

from ironsbot.config.models.messaging import (
    OutboundRateLimitConfig,
    OutboundRateLimitWindowConfig,
)
from ironsbot.core.outbound import DeliveryFailureKind, OutboundMessage, ReplyContext
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from ironsbot.integrations.onebot.replies import send_portable_event_reply
from tests.helpers.onebot_events import group_message_event
from tests.helpers.runtime import build_test_runtime


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    try:
        driver = nonebot.get_driver()
    except ValueError:
        nonebot.init(_env_file=None)
        driver = nonebot.get_driver()
    monkeypatch.setattr(Bot, "_calling_api_hook", set())
    monkeypatch.setattr(Bot, "_called_api_hook", set())
    state = SimpleNamespace(
        error=None,
        block=False,
        entered=asyncio.Event(),
        release=asyncio.Event(),
        calls=[],
    )

    async def api(_adapter: Adapter, _bot: Bot, name: str, **data: Any) -> object:
        if name == "get_login_info":
            return {"nickname": "test"}
        state.calls.append(data)
        state.entered.set()
        if state.block:
            await state.release.wait()
        if state.error is not None:
            raise state.error
        return {"message_id": 123}

    monkeypatch.setattr(Adapter, "_call_api", api)
    runtime = build_test_runtime(
        outbound_config=OutboundRateLimitConfig(
            enabled=True,
            windows=[OutboundRateLimitWindowConfig(window_seconds=60, max_messages=1)],
            cooldown_message="limit reached",
        )
    )
    bot = Bot(Adapter(driver), "1")
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
        ActionFailed(retcode=1200, wording="private-detail"),
    ],
)
async def test_actual_sdk_failures_use_shared_uncertain_settlement(
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
    if isinstance(error, ActionFailed):
        passive = await send_portable_event_reply(
            Mock(send=AsyncMock(side_effect=error)),
            group_message_event("help"),
            message,
        )
        assert passive.failure_kind is result.failure_kind
        assert "private-detail" not in (passive.error_message or "")


@pytest.mark.asyncio
async def test_actual_sdk_cancellation_after_submit_preserves_capacity(
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
