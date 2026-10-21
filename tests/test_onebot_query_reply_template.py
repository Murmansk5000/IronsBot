from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import MessageSegment

from ironsbot.core.outbound import OutboundMessage, SendResult
from ironsbot.integrations.onebot import portable_queries
from ironsbot.services.portable_data_commands import build_portable_data_operation
from ironsbot.services.portable_messaging_commands import (
    build_portable_messaging_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.peak import PeakQueryResult
from tests.helpers.onebot_events import group_message_event


@pytest.mark.asyncio
@pytest.mark.parametrize("message_id", [-12, 12])
async def test_peak_progress_and_image_share_request_reference(message_id: int) -> None:
    from ironsbot.integrations.onebot.replies import send_portable_event_reply
    from ironsbot.services.portable_reply import PortableReply, deliver_portable_reply

    matcher = Mock(
        state={}, send=AsyncMock(return_value={"message_id": 10}), finish=AsyncMock()
    )
    event = group_message_event(message_id=message_id)

    async def send(message: OutboundMessage) -> SendResult:
        return await send_portable_event_reply(cast("Any", matcher), event, message)

    reply = PortableReply(
        OutboundMessage.from_text("progress"),
        follow_up=AsyncMock(return_value=PeakQueryResult(image=b"png").to_outbound()),
    )
    await deliver_portable_reply(reply, send)
    progress = matcher.send.call_args_list[0].args[0]
    assert [part.type for part in progress] == ["reply", "at", "text", "text"]
    assert progress[0] == MessageSegment.reply(message_id)
    assert progress.extract_plain_text() == "\nprogress"
    image = matcher.send.call_args_list[1].args[0]
    assert [part.type for part in image] == ["reply", "image"]
    assert image[0] == MessageSegment.reply(message_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["version", "countdown"])
async def test_data_text_reply_uses_same_template(text: str) -> None:
    matcher = Mock(state={}, send=AsyncMock(return_value={"message_id": 901}))
    operation = build_portable_data_operation(
        Mock(data_version=AsyncMock(return_value=text))
    )
    await portable_queries.make_portable_operation_handler(operation)(
        cast("Any", matcher), {}, group_message_event("数据版本", message_id=-1)
    )
    message = matcher.send.call_args.args[0]
    assert [part.type for part in message] == ["reply", "at", "text", "text"]
    assert message.extract_plain_text() == "\n" + text


@pytest.mark.asyncio
async def test_subscription_menu_keeps_reply_reference_and_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = PortableQuerySessions()
    service = Mock(
        portable_command_actions=(),
        topics=None,
        prepared_subscription_menu=AsyncMock(return_value=([Mock()], "menu")),
    )
    event = group_message_event(message_id=-15)
    sent = []

    async def send(_matcher: Any, current: Any, message: OutboundMessage) -> SendResult:
        from ironsbot.integrations.onebot.message_rendering import (
            render_onebot_outbound_message,
        )
        from ironsbot.integrations.onebot.replies import build_event_reply_message

        sent.append(
            build_event_reply_message(current, render_onebot_outbound_message(message))
        )
        return SendResult(delivered=True, message_id="menu-result")

    monkeypatch.setattr(portable_queries, "send_portable_event_reply", send)
    operation = build_portable_messaging_operations(service, sessions)[
        "messaging.push_subscription"
    ]
    handler = portable_queries.make_portable_query_handler(operation, sessions)
    await handler(Mock(state={}), {}, event)
    prompt = sent[0]
    assert [part.type for part in prompt] == ["reply", "at", "text", "text"]
    assert prompt[0] == MessageSegment.reply(-15)
    assert prompt.extract_plain_text() == "\nmenu"
