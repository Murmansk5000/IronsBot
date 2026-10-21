from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.outbound import SendResult, TextPart
from ironsbot.integrations.onebot import portable_queries
from ironsbot.services.portable_seer_commands import build_portable_rank_help_operation
from ironsbot.services.seer.rank_command_contracts import RANK_HELP_COMMANDS
from tests.helpers.onebot_events import group_message_event, private_message_event


def test_rank_help_uses_every_domain_help_alias() -> None:
    assert RANK_HELP_COMMANDS == (
        "榜单",
        "排行榜",
        "榜单帮助",
        "排行榜帮助",
        "有哪些榜单",
        "可用榜单",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_rank_help_shared_reply(monkeypatch: Any, *, group: bool) -> None:
    sent = AsyncMock(return_value=SendResult(delivered=True, message_id="result"))
    monkeypatch.setattr(portable_queries, "send_portable_event_reply", sent)
    commands: Any = SimpleNamespace(
        format_for_context=lambda *_args, **_kwargs: "【榜单查询】\n成就榜 - 查询榜单"
    )
    operation = build_portable_rank_help_operation(commands, commands)
    event = (group_message_event if group else private_message_event)("榜单")
    matcher: Any = SimpleNamespace(state={})
    await portable_queries.make_portable_operation_handler(operation)(
        matcher, {}, event
    )
    sent.assert_awaited_once()
    assert sent.await_args is not None
    assert sent.await_args.args[:2] == (matcher, event)
    assert isinstance(sent.await_args.args[2].parts[0], TextPart)
    assert "📊【可用榜单】" in sent.await_args.args[2].parts[0].text
    assert "【榜单查询】" in sent.await_args.args[2].parts[0].text
