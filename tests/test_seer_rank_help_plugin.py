from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.outbound import SendResult, TextPart
from ironsbot.services.portable_seer_commands import build_portable_rank_help_operation
from ironsbot.services.seer.rank_command_contracts import RANK_HELP_COMMANDS
from tests.helpers.command_execution import operation_router
from tests.helpers.onebot_events import group_message_event, private_message_event
from tests.helpers.onebot_inputs import message_input_context


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
async def test_rank_help_shared_reply(*, group: bool) -> None:
    sent = AsyncMock(return_value=SendResult(delivered=True, message_id="result"))
    commands: Any = SimpleNamespace(
        format_for_context=lambda *_args, **_kwargs: "【榜单查询】\n成就榜 - 查询榜单"
    )
    operation = build_portable_rank_help_operation(commands, commands)
    event = (group_message_event if group else private_message_event)("榜单")
    context = message_input_context(event)
    await operation_router(operation, context).ingress.handle(context, sent)
    sent.assert_awaited_once()
    assert sent.await_args is not None
    assert isinstance(sent.await_args.args[0].parts[0], TextPart)
    assert "📊【可用榜单】" in sent.await_args.args[0].parts[0].text
    assert "【榜单查询】" in sent.await_args.args[0].parts[0].text
