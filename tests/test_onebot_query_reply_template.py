from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import MessageSegment

from ironsbot.plugins.onebot.messaging import push_subscription_handlers
from ironsbot.plugins.onebot.seer.query.commands import data_queries, peak_queries
from ironsbot.services.seer.peak import PeakQueryResult
from tests.helpers.onebot_events import group_message_event


@pytest.mark.asyncio
@pytest.mark.parametrize("message_id", [-12, 12])
async def test_peak_progress_and_image_share_request_reference(message_id: int) -> None:
    matcher = Mock(state={}, send=AsyncMock(), finish=AsyncMock())
    event = group_message_event(message_id=message_id)
    await peak_queries._report_progress(cast("Any", matcher), event, "progress")
    progress = matcher.send.call_args.args[0]
    assert [part.type for part in progress] == ["reply", "at", "text", "text"]
    assert progress[0] == MessageSegment.reply(message_id)
    assert progress.extract_plain_text() == "\nprogress"
    await peak_queries._finish_result(
        PeakQueryResult(image=b"png"), cast("Any", matcher), event
    )
    image = matcher.finish.call_args.args[0]
    assert [part.type for part in image] == ["reply", "image"]
    assert image[0] == MessageSegment.reply(message_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["version", "countdown"])
async def test_data_text_reply_uses_same_template(text: str) -> None:
    matcher = Mock(state={}, finish=AsyncMock())
    await data_queries._finish_query(
        AsyncMock(return_value=text),
        matcher=cast("Any", matcher),
        event=group_message_event(message_id=-1),
        references=None,
    )
    message = matcher.finish.call_args.args[0]
    assert [part.type for part in message] == ["reply", "at", "text", "text"]
    assert message.extract_plain_text() == "\n" + text


@pytest.mark.asyncio
async def test_subscription_menu_keeps_reply_reference_and_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = group_message_event(message_id=-15)
    loop = AsyncMock()
    monkeypatch.setattr(push_subscription_handlers, "enter_prompt_loop", loop)
    monkeypatch.setattr(
        push_subscription_handlers,
        "is_group_push_subscription_manager",
        lambda _messaging, _event: True,
    )
    flow = SimpleNamespace(
        begin=lambda *_args: ("session", 1),
        rule=lambda *_args: None,
        reply_check=lambda *_args: None,
        namespace="subscription",
    )
    monkeypatch.setattr(push_subscription_handlers, "PUSH_SUBSCRIPTION_FLOW", flow)
    service = Mock(
        prepared_subscription_menu=AsyncMock(return_value=([Mock()], "menu"))
    )
    await push_subscription_handlers.handle_push_subscription_menu(
        cast("Any", Mock(state={})), event, {}, messaging=service
    )
    assert loop.await_args is not None
    prompt = loop.await_args.kwargs["prompt"]
    assert [part.type for part in prompt] == ["reply", "at", "text", "text"]
    assert prompt[0] == MessageSegment.reply(-15)
    assert prompt.extract_plain_text() == "\nmenu"
