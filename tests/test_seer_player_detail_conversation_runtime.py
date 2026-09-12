import asyncio
from datetime import datetime, timezone
from importlib import import_module
from types import SimpleNamespace
from typing import Any, cast, get_type_hints
from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.exception import FinishedException
from nonebot.matcher import current_event
from pytest import MonkeyPatch

from ironsbot.config.models.seer import SeerConfig
from ironsbot.integrations.onebot.conversations import event_conversation_session_id
from ironsbot.integrations.onebot.matcher_support import (
    RUNTIME_CONTEXT_TOKEN_STATE_KEY,
    register_runtime_context,
)
from ironsbot.integrations.onebot.prompt_sessions import (
    QUEUED_CONVERSATION_TICKET_STATE_KEY,
    QUEUED_CONVERSATION_TOKEN_STATE_KEY,
    PromptSessionManager,
)
from ironsbot.plugins.onebot.seer.query.commands import player_detail_conversation
from ironsbot.plugins.onebot.seer.query.commands.player_context import PLAYER_ID_KEY
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_detail_service import PlayerDetailService
from ironsbot.services.seer.player_formatting_common import format_player_data_time
from ironsbot.services.seer.player_query import (
    PLAYER_COLLECTION_KEY,
    PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY,
    PLAYER_DETAIL_COMMANDS_KEY,
    PLAYER_PEAK_KEY,
)
from ironsbot.services.seer.player_shortcut_contracts import PlayerShortcutCommand
from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.rank_models import (
    PeakSeasonRankSummary,
    PlayerRankSummary,
    RankLookupResult,
    RankSummaryProgress,
)
from ironsbot.services.seer.sequ_extra import (
    UnityPartOneInfo,
    UnityPeakFetchResult,
    UnityPeakInfo,
)
from tests.helpers.onebot_events import group_message_event


def _ensure_nonebot_initialized() -> None:
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()


@pytest.mark.parametrize(
    ("module_name", "handler_names"),
    [
        (
            "ironsbot.plugins.onebot.seer.query.commands.player_detail_conversation",
            ["handle_player_detail_reply"],
        ),
        (
            "ironsbot.plugins.onebot.messaging.push_subscription_handlers",
            ["handle_push_subscription_menu", "handle_push_subscription_select"],
        ),
    ],
)
def test_prompt_handler_annotations_resolve_at_runtime(
    monkeypatch: MonkeyPatch,
    module_name: str,
    handler_names: list[str],
) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", "config.example.toml")
    _ensure_nonebot_initialized()

    module = import_module(module_name)

    for handler_name in handler_names:
        hints = get_type_hints(getattr(module, handler_name))

        assert {"matcher", "event", "state"} <= set(hints)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("interrupted", [False, True])
@pytest.mark.parametrize("detail_key", [PLAYER_COLLECTION_KEY, PLAYER_PEAK_KEY])
async def test_detail_publication_respects_actual_menu_lifecycle(  # noqa: PLR0915 - service-to-publication lifecycle
    monkeypatch: MonkeyPatch,
    detail_key: str,
    *,
    cancelled: bool,
    interrupted: bool,
) -> None:
    observed_at = 1_800_000_000.0
    rank_at = observed_at - 120
    monkeypatch.setattr(
        "ironsbot.core.time.now",
        lambda: datetime.fromtimestamp(observed_at, tz=timezone.utc),
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_detail_service.now",
        lambda: datetime.fromtimestamp(observed_at, tz=timezone.utc),
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_part_one",
        AsyncMock(return_value=UnityPartOneInfo(pet_kind_num=100, skin_num=20)),
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_peak_partial",
        AsyncMock(
            return_value=UnityPeakFetchResult(
                UnityPeakInfo(current_z_score=1421, current_z_all=10),
                frozenset(("standard", "wild", "expert")),
                fetched_at=observed_at,
            )
        ),
    )
    manager = PromptSessionManager()
    event = group_message_event("1")
    namespace = player_detail_conversation.PLAYER_DETAIL_NAMESPACE
    session_id = event_conversation_session_id(namespace, event)
    state: dict[str, Any] = {
        PLAYER_ID_KEY: 712345678,
        PLAYER_DETAIL_COMMANDS_KEY: ("1", "0"),
        PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY: (("1", detail_key),),
        RUNTIME_CONTEXT_TOKEN_STATE_KEY: register_runtime_context(manager, None),
    }
    context = manager.start_queued_conversation(
        namespace=namespace,
        event_session_id=event.get_session_id(),
        conversation_session_id=session_id,
        state=state,
        handlers=[],
        reply_check=lambda incoming: incoming.get_plaintext() in {"1", "0"},
        parallel=True,
    )
    ticket = await context.acquire()
    assert ticket is not None
    context.mark_dispatched(ticket)
    state[QUEUED_CONVERSATION_TOKEN_STATE_KEY] = context.token
    state[QUEUED_CONVERSATION_TICKET_STATE_KEY] = ticket
    started, release = asyncio.Event(), asyncio.Event()

    async def fetch_ranks(
        *_args: Any, progress: RankSummaryProgress, **_kwargs: Any
    ) -> PlayerRankSummary | PeakSeasonRankSummary:
        key = "achieve" if detail_key == PLAYER_COLLECTION_KEY else "expert_peak"
        progress.completed[key] = RankLookupResult(
            title="completed rank",
            score_name="score",
            rank=4,
            score=1421,
            queried=True,
            fetched_at=rank_at,
        )
        progress.current_title = "pending rank"
        started.set()
        await release.wait()
        if interrupted:
            raise TimeoutError
        if detail_key == PLAYER_COLLECTION_KEY:
            return PlayerRankSummary.from_results(progress.completed)
        return PeakSeasonRankSummary.from_results(progress.completed)

    config = SeerConfig()
    rank = SimpleNamespace(
        config=config.rank,
        current_peak_sub_key=lambda: 7,
        fetch_player_summary=AsyncMock(side_effect=fetch_ranks),
        fetch_peak_summary=AsyncMock(side_effect=fetch_ranks),
    )
    game = SimpleNamespace(
        get_user_info=AsyncMock(return_value=SimpleNamespace(nick="tester")),
        get_more_user_info=AsyncMock(
            return_value=SimpleNamespace(total_achieve=1421, pet_all_num=200)
        ),
    )
    details = PlayerDetailService(
        config,
        cast("Any", rank),
        cast("Any", SimpleNamespace(config=SimpleNamespace(enabled=False))),
        lambda coroutine, *, name: asyncio.create_task(coroutine, name=name),
    )
    replies: list[QueryReply] = []

    async def query(
        command: PlayerShortcutCommand, *_args: Any, **_kwargs: Any
    ) -> QueryReply:
        reply = await details.shortcut(cast("Any", game), command, state[PLAYER_ID_KEY])
        replies.append(reply)
        return reply

    service = SimpleNamespace(shortcut=AsyncMock(side_effect=query))
    matcher = SimpleNamespace(
        state=state, send=AsyncMock(return_value={"message_id": 99})
    )
    event_token = current_event.set(event)
    task = asyncio.create_task(
        player_detail_conversation.handle_player_detail_reply(
            cast("Any", service),
            PlayerDetailExtensionRegistry(),
            cast("Any", object()),
            cast("Any", matcher),
            event,
            state,
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        if cancelled:
            manager.cancel_queued_conversation(state)
        version = manager.acquire(session_id)
        next_menu_rule = manager.make_rule(session_id, version, lambda _event: True)
        release.set()
        with pytest.raises(FinishedException):
            await task
        assert len(replies) == 1
        assert replies[0].complete is not interrupted
        assert replies[0].fetched_at == rank_at
        kind = "collection" if detail_key == PLAYER_COLLECTION_KEY else "peak"
        cached = await details.cached_or_inflight_reply(state[PLAYER_ID_KEY], kind)
        if interrupted:
            assert cached is None
        else:
            assert cached is replies[0]
            reused = await details.shortcut(
                cast("Any", game),
                PlayerShortcutCommand(kind=kind, player_id=state[PLAYER_ID_KEY]),
                state[PLAYER_ID_KEY],
            )
            assert reused is replies[0]
        assert (
            rank.fetch_player_summary.await_count + rank.fetch_peak_summary.await_count
            == 1
        )
        if cancelled:
            matcher.send.assert_not_awaited()
            assert await next_menu_rule(cast("Any", object()), event, {})
        else:
            matcher.send.assert_awaited_once()
            sent = matcher.send.await_args
            assert sent is not None
            message = str(sent.args[0])
            assert replies[0].text in message
            assert format_player_data_time(rank_at) in message
            assert ("查询超时" in message) is interrupted
            assert "1421" in message
            assert "第4" in message
            assert "未上榜" not in message
            assert context.matches(group_message_event("1"))
            assert context.matches(group_message_event("0"))
            assert not context.matches(group_message_event("收集"))
            assert not context.matches(
                group_message_event("1", user_id=event.user_id + 1)
            )
            assert not context.matches(
                group_message_event("1", group_id=event.group_id + 1)
            )
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        manager.cancel_queued_conversation(state)
        manager.finish_queued_conversation(state)
        current_event.reset(event_token)
