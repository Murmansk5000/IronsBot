# SPDX-License-Identifier: MIT
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.outbound import SendResult
from ironsbot.integrations.onebot import portable_queries
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.services.portable_query_operations import build_query_operation
from ironsbot.services.portable_query_sessions import (
    PortableQuerySessions,
    QueryOperationSpec,
)
from ironsbot.services.seer.query_result import QueryChoice, QueryReply, QueryResult
from tests.helpers.onebot_events import group_message_event, private_message_event


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_direct_query_uses_shared_reply_transport(
    monkeypatch: Any, *, group: bool
) -> None:
    sent = AsyncMock(return_value=SendResult(delivered=True, message_id="result"))
    monkeypatch.setattr(portable_queries, "send_portable_event_reply", sent)
    sessions = PortableQuerySessions()
    result = QueryReply(leading_text="before", image=b"image", text="after")
    operation = build_query_operation(
        sessions,
        QueryOperationSpec(
            parser=lambda text: text,
            search=AsyncMock(return_value=QueryResult(reply=result)),
            select=AsyncMock(),
            prompt_title="选择精灵",
        ),
    )
    event = (group_message_event if group else private_message_event)("测试技能")
    matcher: Any = SimpleNamespace(state={})
    await portable_queries.make_portable_query_handler(operation, sessions)(
        matcher, {}, event
    )
    sent.assert_awaited_once_with(matcher, event, result.to_outbound())


@pytest.mark.asyncio
async def test_choice_query_reserves_numeric_menu_before_search(
    monkeypatch: Any,
) -> None:
    sessions = PortableQuerySessions()
    event = group_message_event("测试技能")
    context = message_input_context(event)

    async def search(_text: str) -> QueryResult[int]:
        assert sessions.recognizes_response("7", context)
        return QueryResult(choices=(QueryChoice("候选精灵", "100", 100),))

    sent = AsyncMock(return_value=SendResult(delivered=True, message_id="menu"))
    monkeypatch.setattr(portable_queries, "send_portable_event_reply", sent)
    operation = build_query_operation(
        sessions,
        QueryOperationSpec(
            parser=lambda text: text,
            search=search,
            select=AsyncMock(),
            prompt_title="选择精灵",
        ),
    )
    matcher: Any = SimpleNamespace(state={})
    await portable_queries.make_portable_query_handler(operation, sessions)(
        matcher, {}, event
    )
    assert sessions.menu_anchor(context) == "menu"
    assert sessions.has_active_session(context)
