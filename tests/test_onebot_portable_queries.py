from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.exception import FinishedException

nonebot.init()

from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.semantic_requests import ActionDefinition, SemanticTarget
from ironsbot.integrations.onebot import portable_queries
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
    QueryOperationSpec,
    build_query_operation,
)
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.query_result import QueryChoice, QueryReply, QueryResult
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from collections.abc import Awaitable


async def _run(awaitable: Awaitable[None]) -> None:
    await awaitable


def _matcher() -> Any:
    return SimpleNamespace(state={})


def test_query_reserves_numeric_input_before_portable_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    sessions = PortableQuerySessions()

    async def reserve(*_args: object, **_kwargs: object) -> None:
        order.append("reserve")

    async def search(_argument: str) -> QueryResult[int]:
        assert order == ["reserve"]
        order.append("search")
        return QueryResult(choices=(QueryChoice("candidate", "101", 101),))

    async def select(value: int) -> QueryResult[object]:
        return QueryResult(reply=QueryReply(text=str(value)))

    async def enter(*_args: object, **kwargs: object) -> None:
        order.append("activate")
        assert kwargs["prompt"] is not None
        raise FinishedException

    monkeypatch.setattr(portable_queries, "begin_event_reply_conversation", reserve)
    monkeypatch.setattr(portable_queries, "enter_event_reply_conversation", enter)
    operation = build_query_operation(
        sessions,
        QueryOperationSpec(
            parser=lambda text: text.removeprefix("精灵") or None,
            search=search,
            select=select,
            prompt_title="选择精灵",
            not_found_message="未找到",
        ),
    )
    handler = portable_queries.make_portable_query_handler(
        operation,
        sessions,
        ActionDefinition("seer_pet_info", "精灵查询"),
    )
    event = group_message_event("精灵雷伊")

    with pytest.raises(FinishedException):
        asyncio.run(_run(handler(_matcher(), {}, event)))

    assert order == ["reserve", "search", "activate"]


def test_operation_handler_delivers_without_reserving_numeric_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = AsyncMock(return_value=OutboundMessage.from_text("done"))
    reserve = AsyncMock()
    deliver = AsyncMock()
    monkeypatch.setattr(portable_queries, "begin_event_reply_conversation", reserve)
    monkeypatch.setattr(portable_queries, "_deliver", deliver)
    handler = portable_queries.make_portable_query_handler(
        operation,
        PortableQuerySessions(),
        ActionDefinition("seer.player.collection", "收集与排行"),
        reserve_session=False,
    )
    event = group_message_event("收集")

    asyncio.run(_run(handler(_matcher(), {}, event)))

    reserve.assert_not_awaited()
    operation.assert_awaited_once()
    assert operation.await_args is not None
    assert operation.await_args.args[0] == "收集"
    deliver.assert_awaited_once()


def test_query_menu_uses_portable_selection_and_semantic_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = PortableQuerySessions()

    async def search(_argument: str) -> QueryResult[int]:
        return QueryResult(
            choices=(
                QueryChoice(
                    "candidate",
                    "101",
                    101,
                    semantic_target=SemanticTarget("pet:101", "candidate"),
                ),
            )
        )

    async def select(value: int) -> QueryResult[object]:
        return QueryResult(reply=QueryReply(text=f"selected:{value}"))

    captured: dict[str, object] = {}

    async def reserve(*_args: object, **kwargs: object) -> None:
        captured.update(kwargs)

    async def enter(*_args: object, **kwargs: object) -> None:
        captured.update(kwargs)
        raise FinishedException

    monkeypatch.setattr(portable_queries, "begin_event_reply_conversation", reserve)
    monkeypatch.setattr(portable_queries, "enter_event_reply_conversation", enter)
    operation = build_query_operation(
        sessions,
        QueryOperationSpec(
            parser=lambda text: text.removeprefix("精灵") or None,
            search=search,
            select=select,
            prompt_title="选择精灵",
            not_found_message="未找到",
        ),
    )
    handler = portable_queries.make_portable_query_handler(
        operation,
        sessions,
        ActionDefinition("seer_pet_info", "精灵查询"),
    )
    owner = group_message_event("精灵雷伊")
    with pytest.raises(FinishedException):
        asyncio.run(_run(handler(_matcher(), {}, owner)))

    resolver = cast("Any", captured["queue_semantic_request_resolver"])
    selected = group_message_event(
        "1",
        user_id=owner.user_id,
        group_id=owner.group_id,
    )
    request = resolver(selected, {})
    assert request is not None
    assert request.target == SemanticTarget("pet:101", "candidate")

    selection_handler = cast("Any", captured["handlers"])[0]
    deliver = AsyncMock()
    monkeypatch.setattr(portable_queries, "_deliver", deliver)
    asyncio.run(selection_handler(_matcher(), selected, {}))

    deliver.assert_awaited_once()
    assert deliver.await_args is not None
    result = deliver.await_args.args[2]
    assert isinstance(result, OutboundMessage)
    assert not sessions.has_pending(message_input_context(owner))


def test_deferred_menu_rejoins_durable_input_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = PortableQuerySessions()
    order: list[str] = []

    async def operation(
        text: str,
        context: Any,
    ) -> PortableReply:
        del text

        async def follow_up() -> OutboundMessage:
            return sessions.offer_menu(
                context,
                PortableMenuSpec(
                    choices=("choice",),
                    select=_selected,
                    prompt=OutboundMessage.from_text("choose"),
                ),
            )

        return PortableReply(
            OutboundMessage.from_text("progress"),
            follow_up=follow_up,
        )

    async def _selected(value: str) -> OutboundMessage:
        return OutboundMessage.from_text(value)

    async def reserve(*_args: object, **_kwargs: object) -> None:
        order.append("reserve")

    async def deliver(
        _matcher: object,
        _event: object,
        result: object,
    ) -> None:
        order.append("deliver")
        assert isinstance(result, PortableReply)
        assert result.follow_up is not None
        await result.follow_up()

    async def enter(*_args: object, **kwargs: object) -> None:
        order.append("activate")
        assert "prompt" not in kwargs
        raise FinishedException

    monkeypatch.setattr(portable_queries, "begin_event_reply_conversation", reserve)
    monkeypatch.setattr(portable_queries, "_deliver", deliver)
    monkeypatch.setattr(portable_queries, "enter_event_reply_conversation", enter)
    handler = portable_queries.make_portable_query_handler(
        operation,
        sessions,
        ActionDefinition("maintenance", "maintenance"),
    )

    with pytest.raises(FinishedException):
        asyncio.run(_run(handler(_matcher(), {}, group_message_event("command"))))

    assert order == ["reserve", "deliver", "activate"]
