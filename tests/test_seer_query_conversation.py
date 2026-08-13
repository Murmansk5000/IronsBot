# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import nonebot
from nonebot.exception import FinishedException

nonebot.init()

from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.plugins.seer.query import query_conversation
from ironsbot.services.seer.query_result import QueryChoice, QueryReply, QueryResult
from tests.helpers.onebot_events import group_message_event, private_message_event

if TYPE_CHECKING:
    from collections.abc import Awaitable


async def _run(awaitable: Awaitable[None]) -> None:
    await awaitable


def test_direct_group_query_reply_mentions_sender(monkeypatch: Any) -> None:
    send_reply = AsyncMock(side_effect=FinishedException)
    monkeypatch.setattr(query_conversation, "send_query_reply", send_reply)
    monkeypatch.setattr(
        query_conversation,
        "begin_event_reply_conversation",
        AsyncMock(),
    )
    handler = query_conversation.make_query_handler(
        AsyncMock(return_value=QueryResult(reply=QueryReply(image=b"image"))),
        AsyncMock(),
        "选择精灵",
        ActionDefinition("seer.pet.skill", "精灵技能"),
    )

    event = group_message_event("梦天睡神技能")
    with suppress(FinishedException):
        asyncio.run(_run(
            handler(
                cast("Any", object()),
                {},
                event,
            )
        ))

    send_reply.assert_awaited_once_with(
        QueryReply(image=b"image"),
        event,
        finish=True,
    )


def test_direct_private_query_reply_does_not_mention_sender(monkeypatch: Any) -> None:
    send_reply = AsyncMock(side_effect=FinishedException)
    monkeypatch.setattr(query_conversation, "send_query_reply", send_reply)
    monkeypatch.setattr(
        query_conversation,
        "begin_event_reply_conversation",
        AsyncMock(),
    )
    handler = query_conversation.make_query_handler(
        AsyncMock(return_value=QueryResult(reply=QueryReply(text="结果"))),
        AsyncMock(),
        "选择精灵",
        ActionDefinition("seer.pet.skill", "精灵技能"),
    )
    event = private_message_event("梦天睡神技能")

    with suppress(FinishedException):
        asyncio.run(_run(handler(cast("Any", object()), {}, event)))

    send_reply.assert_awaited_once_with(
        QueryReply(text="结果"),
        event,
        finish=True,
    )


def test_choice_query_reserves_numeric_menu_before_search(
    monkeypatch: Any,
) -> None:
    order: list[str] = []

    async def reserve(*_args: object, **_kwargs: object) -> None:
        order.append("reserve")

    async def search(_: str) -> QueryResult[int]:
        assert order == ["reserve"]
        order.append("search")
        return QueryResult(
            choices=(QueryChoice("候选精灵", "100", 100),),
        )

    async def enter_prompt(*_args: object, **_kwargs: object) -> None:
        order.append("activate")
        raise FinishedException

    reserve_mock = AsyncMock(side_effect=reserve)
    monkeypatch.setattr(
        query_conversation,
        "begin_event_reply_conversation",
        reserve_mock,
    )
    monkeypatch.setattr(query_conversation, "enter_prompt", enter_prompt)
    handler = query_conversation.make_query_handler(
        search,
        AsyncMock(),
        "选择精灵",
        ActionDefinition("seer.pet.skill", "精灵技能"),
    )
    event = group_message_event("阿克希亚技能")

    with suppress(FinishedException):
        asyncio.run(_run(handler(cast("Any", object()), {}, event)))

    assert order == ["reserve", "search", "activate"]
    call = reserve_mock.await_args
    assert call is not None
    assert call.kwargs["namespace"] == "selection_prompt"
    assert call.kwargs["pending_reply_check"](
        group_message_event("7"),
    )
    assert call.kwargs["reply_check"](
        group_message_event("7"),
    )


def test_query_reply_only_mentions_sender_in_group(monkeypatch: Any) -> None:
    class FakeMessage:
        finish = AsyncMock(side_effect=FinishedException)
        send = AsyncMock()

    message = FakeMessage()
    monkeypatch.setattr(query_conversation, "build_reply", lambda _: message)

    with suppress(FinishedException):
        asyncio.run(
            query_conversation.send_query_reply(
                QueryReply(text="结果"),
                group_message_event(),
                finish=True,
            )
        )

    message.finish.assert_awaited_once_with(at_sender=True)
    asyncio.run(
        query_conversation.send_query_reply(
            QueryReply(text="结果"),
            private_message_event(),
            finish=False,
        )
    )
    message.send.assert_awaited_once_with(at_sender=False)
