from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.outbound import OutboundMessage
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.message_segments import onebot_message_text
from ironsbot.services.portable_data_commands import build_portable_data_operation
from ironsbot.services.portable_messaging_commands import (
    build_portable_messaging_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.peak import PeakQueryResult
from tests.helpers.command_execution import operation_router
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from types import SimpleNamespace

pytest_plugins = ("tests.test_shared_onebot_ingress",)


@pytest.mark.asyncio
@pytest.mark.parametrize("message_id", [-12, 12])
async def test_peak_progress_and_image_share_request_reference(
    runtime: SimpleNamespace, message_id: int
) -> None:
    from ironsbot.services.portable_reply import PortableReply

    event = group_message_event(message_id=message_id)

    reply = PortableReply(
        OutboundMessage.from_text("progress"),
        follow_up=AsyncMock(return_value=PeakQueryResult(image=b"png").to_outbound()),
    )
    context = message_input_context(event)
    router = operation_router(AsyncMock(return_value=reply), context)
    await router.ingress.handle(
        context, partial(runtime.messenger.reply_from, runtime.bot, context)
    )
    progress, image = (sent["message"] for sent in runtime.sends)
    assert [part["type"] for part in progress] == ["reply", "at", "text", "text"]
    assert progress[0] == {"type": "reply", "data": {"id": str(message_id)}}
    assert onebot_message_text(progress) == "\nprogress"
    assert [part["type"] for part in image] == ["reply", "image"]
    assert image[0] == {"type": "reply", "data": {"id": str(message_id)}}


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["version", "countdown"])
async def test_data_text_reply_uses_same_template(
    runtime: SimpleNamespace, text: str
) -> None:
    operation = build_portable_data_operation(
        Mock(data_version=AsyncMock(return_value=text))
    )
    context = message_input_context(group_message_event("数据版本", message_id=-1))
    await operation_router(operation, context).ingress.handle(
        context, partial(runtime.messenger.reply_from, runtime.bot, context)
    )
    (sent,) = runtime.sends
    message = sent["message"]
    assert [part["type"] for part in message] == ["reply", "at", "text", "text"]
    assert onebot_message_text(message) == "\n" + text


@pytest.mark.asyncio
async def test_subscription_menu_keeps_reply_reference_and_sender(
    runtime: SimpleNamespace,
) -> None:
    sessions = PortableQuerySessions()
    service = Mock(
        portable_command_actions=(),
        topics=None,
        prepared_subscription_menu=AsyncMock(return_value=([Mock()], "menu")),
    )
    event = group_message_event(message_id=-15)
    operation = build_portable_messaging_operations(service, sessions)[
        "messaging.push_subscription"
    ]
    context = message_input_context(event)
    await operation_router(operation, context, sessions).ingress.handle(
        context, partial(runtime.messenger.reply_from, runtime.bot, context)
    )
    (sent,) = runtime.sends
    prompt = sent["message"]
    assert [part["type"] for part in prompt] == ["reply", "at", "text", "text"]
    assert prompt[0] == {"type": "reply", "data": {"id": "-15"}}
    assert onebot_message_text(prompt) == "\nmenu"
