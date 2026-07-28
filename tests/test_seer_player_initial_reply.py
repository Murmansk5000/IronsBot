# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from ironsbot.plugins.seer.query.commands import player
from ironsbot.services.seer.player_query import PlayerQuerySectionPlan
from ironsbot.services.seer.player_service import PendingPlayerQuery
from tests.helpers.onebot_events import group_message_event


def test_initial_player_reply_precedes_background_refresh(
    monkeypatch: Any,
) -> None:
    pending = PendingPlayerQuery(
        player_id=904_346_786,
        user_info=SimpleNamespace(nick="faye"),
        more_info=object(),
        player_message="玩家信息",
        section_plan=PlayerQuerySectionPlan(
            has_collection=True,
            needs_peak_section=True,
            has_autocard_rank=True,
            show_local_rank=False,
            needs_online_info=True,
            local_rank_enabled=False,
        ),
    )
    service = SimpleNamespace(
        record_returned_query=Mock(),
        start_background_refresh=Mock(),
    )
    send_prompt = AsyncMock()
    monkeypatch.setattr(
        player,
        "send_player_info_with_detail_prompt",
        send_prompt,
    )
    event = group_message_event("米米号904346786")
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
    )

    asyncio.run(
        player._send_pending_player_query(
            dependencies,
            cast("Any", object()),
            event,
            {},
            pending,
        )
    )

    service.record_returned_query.assert_not_called()
    service.start_background_refresh.assert_not_called()
    sent_call = send_prompt.await_args
    assert sent_call is not None
    callback = sent_call.kwargs["on_sent"]
    callback()

    service.record_returned_query.assert_called_once_with(event.user_id, pending)
    service.start_background_refresh.assert_called_once_with(
        pending,
        group_id=event.group_id,
    )
