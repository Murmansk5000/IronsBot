# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from base64 import b64encode
from contextlib import suppress
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.exception import FinishedException

nonebot.init()

from ironsbot.core.outbound import SendResult
from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot import portable_queries
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.plugins.onebot.seer.query import query_conversation
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.query_result import QueryChoice, QueryReply, QueryResult
from tests.helpers.onebot_events import group_message_event, private_message_event

if TYPE_CHECKING:
    from collections.abc import Awaitable


async def _run(awaitable: Awaitable[None]) -> None:
    await awaitable


@pytest.mark.parametrize("group", [False, True])
def test_direct_query_uses_shared_reply_transport(
    monkeypatch: Any, *, group: bool
) -> None:
    send_reply = AsyncMock(return_value=SendResult(delivered=True, message_id="result"))
    monkeypatch.setattr(portable_queries, "send_portable_event_reply", send_reply)
    handler = query_conversation.make_query_handler(
        AsyncMock(return_value=QueryResult(reply=QueryReply(image=b"image"))),
        AsyncMock(),
        "选择精灵",
        ActionDefinition("seer.pet.skill", "精灵技能"),
    )

    event = (group_message_event if group else private_message_event)("梦天睡神技能")
    matcher = cast("Any", object())
    asyncio.run(_run(handler(matcher, {}, event)))
    send_reply.assert_awaited_once_with(
        matcher, event, QueryReply(image=b"image").to_outbound()
    )


def test_choice_query_reserves_numeric_menu_before_search(
    monkeypatch: Any,
) -> None:
    sessions = PortableQuerySessions()
    event = group_message_event("阿克希亚技能")
    context = message_input_context(event)

    async def search(_: str) -> QueryResult[int]:
        assert sessions.recognizes_response("7", context)
        return QueryResult(
            choices=(QueryChoice("候选精灵", "100", 100),),
        )

    sent = AsyncMock(return_value=SendResult(delivered=True, message_id="menu"))
    monkeypatch.setattr(portable_queries, "send_portable_event_reply", sent)
    handler = query_conversation.make_query_handler(
        search,
        AsyncMock(),
        "选择精灵",
        ActionDefinition("seer.pet.skill", "精灵技能"),
        sessions=sessions,
    )
    asyncio.run(_run(handler(cast("Any", SimpleNamespace(state={})), {}, event)))
    assert sessions.menu_anchor(context) == "menu"
    assert sessions.has_active_session(context)


def test_query_reply_only_mentions_sender_in_group(monkeypatch: Any) -> None:
    finish = AsyncMock(side_effect=FinishedException)
    send = AsyncMock()
    monkeypatch.setattr(query_conversation.Matcher, "finish", finish)
    monkeypatch.setattr(query_conversation.Matcher, "send", send)

    with suppress(FinishedException):
        asyncio.run(
            query_conversation.send_query_reply(
                QueryReply(text="结果"),
                group_message_event(),
                finish=True,
            )
        )

    assert finish.await_args is not None
    assert str(finish.await_args.args[0]) == "结果"
    assert finish.await_args.kwargs == {"at_sender": True}
    asyncio.run(
        query_conversation.send_query_reply(
            QueryReply(text="结果"),
            private_message_event(),
            finish=False,
        )
    )
    assert send.await_args is not None
    assert str(send.await_args.args[0]) == "结果"
    assert send.await_args.kwargs == {"at_sender": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("image", [None, b"png-content"])
async def test_query_reply_preserves_content_order_and_image_failure(
    monkeypatch: Any, image: bytes | None
) -> None:
    send = AsyncMock()
    monkeypatch.setattr(query_conversation.Matcher, "send", send)
    await query_conversation.send_query_reply(
        QueryReply(
            leading_text="before", image=image, image_error="failed", text="after"
        ),
        private_message_event(),
        finish=False,
    )
    assert send.await_args is not None
    message = send.await_args.args[0]
    if image is None:
        assert message.extract_plain_text() == "beforefailed\nafter"
    else:
        assert [segment.type for segment in message] == [
            "reply",
            "text",
            "image",
            "text",
        ]
        assert message[1].data["text"] == "before"
        assert message[2].data["file"] == "base64://" + b64encode(image).decode()
        assert message[3].data["text"] == "after"
        assert send.await_args.kwargs == {}
