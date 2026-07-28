from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.plugins.seer.rank_help import handle_rank_help_entry
from tests.helpers.onebot_events import group_message_event, private_message_event

if TYPE_CHECKING:
    from nonebot.matcher import Matcher


@pytest.mark.asyncio
async def test_rank_help_replies_to_group_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[object, object, str]] = []

    async def capture(matcher: object, event: object, message: str) -> None:
        sent.append((matcher, event, message))

    monkeypatch.setattr(
        "ironsbot.plugins.seer.rank_help.finish_event_reply",
        capture,
    )
    event = group_message_event("榜单", user_id=123456)

    matcher = cast("Matcher", object())
    await handle_rank_help_entry(matcher, event)

    assert len(sent) == 1
    assert sent[0][0] is matcher
    assert sent[0][1] is event
    assert "【可用榜单】" in sent[0][2]


@pytest.mark.asyncio
async def test_rank_help_uses_same_reply_path_in_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[object, object, str]] = []

    async def capture(matcher: object, event: object, message: str) -> None:
        sent.append((matcher, event, message))

    monkeypatch.setattr(
        "ironsbot.plugins.seer.rank_help.finish_event_reply",
        capture,
    )
    event = private_message_event("排行榜")
    matcher = cast("Matcher", object())

    await handle_rank_help_entry(matcher, event)

    assert len(sent) == 1
    assert sent[0][0] is matcher
    assert sent[0][1] is event
