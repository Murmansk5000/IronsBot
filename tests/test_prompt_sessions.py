from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from nonebot.matcher import Matcher, current_event

from ironsbot.runtime.matchers import (
    MatcherRegistry,
    PromptSessionManager,
    begin_queued_conversation,
)
from ironsbot.runtime.prompt_sessions import _QueuedConversation
from tests.helpers.onebot_events import private_message_event

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.runtime.matcher_contracts import CommandCooldown


def test_start_queued_conversation_closes_older_namespace_menu_for_same_session() -> (
    None
):
    manager = PromptSessionManager()
    owner = private_message_event("动态", user_id=2, self_id=1)
    digit = private_message_event("5", user_id=2, self_id=1)

    dynamic = manager.start_queued_conversation(
        namespace="bilibili_dynamic_menu",
        event_session_id=owner.get_session_id(),
        state={},
        reply_check=lambda event: event.get_plaintext().strip().isdigit(),
        handlers=[],
    )
    assert manager.matching_queued_conversation(digit) is dynamic

    subscription = manager.start_queued_conversation(
        namespace="message_push_subscription",
        event_session_id=owner.get_session_id(),
        state={},
        reply_check=lambda event: event.get_plaintext().strip().isdigit(),
        handlers=[],
    )

    assert not dynamic.active
    assert manager.matching_queued_conversation(digit) is subscription


def test_start_queued_conversation_keeps_other_sessions_open() -> None:
    manager = PromptSessionManager()
    dynamic = manager.start_queued_conversation(
        namespace="bilibili_dynamic_menu",
        event_session_id="private_2",
        state={},
        reply_check=lambda _event: True,
        handlers=[],
    )
    manager.start_queued_conversation(
        namespace="message_push_subscription",
        event_session_id="private_3",
        state={},
        reply_check=lambda _event: True,
        handlers=[],
    )

    assert dynamic.active
    assert (
        manager.queued_conversation_for(
            namespace="bilibili_dynamic_menu",
            event_session_id="private_2",
        )
        is dynamic
    )


@pytest.mark.asyncio
async def test_begin_queued_conversation_takeover_cancels_other_namespace_pending() -> (
    None
):
    manager = PromptSessionManager()
    registry = MatcherRegistry(
        cooldown=cast("CommandCooldown", object()),
        priorities=object(),
        prompt_session_manager=manager,
    )
    event = private_message_event("td", user_id=2, self_id=1)

    async def begin(namespace: str) -> None:
        state = registry._with_runtime_hooks({})["state"]
        matcher = cast("Matcher", SimpleNamespace(state=state))
        event_token = current_event.set(event)
        try:
            await begin_queued_conversation(
                matcher,
                [],
                namespace=namespace,
                pending_reply_check=lambda _event: True,
                queue_reply_check=lambda _event: True,
            )
        finally:
            current_event.reset(event_token)

    await begin("bilibili_dynamic_menu")
    dynamic = manager.queued_conversation_for(
        namespace="bilibili_dynamic_menu",
        event_session_id=event.get_session_id(),
    )
    assert dynamic is not None

    await begin("message_push_subscription")
    subscription = manager.queued_conversation_for(
        namespace="message_push_subscription",
        event_session_id=event.get_session_id(),
    )

    assert subscription is not None
    assert not dynamic.active
    assert manager.matching_queued_conversation(event) is subscription


def test_matching_queued_conversation_prefers_newest_coexisting_menu() -> None:
    manager = PromptSessionManager()
    event = private_message_event("1", user_id=2, self_id=1)
    session_id = event.get_session_id()

    def choice_check(next_event: Event) -> bool:
        return next_event.get_plaintext().strip() == "1"

    older = _QueuedConversation(
        token="older-token",
        key=f"older:{session_id}",
        namespace="older",
        event_session_id=session_id,
        owner_user_id=event.user_id,
        state={},
        reply_check=choice_check,
        group_reply_check=None,
        handlers=[],
    )
    newer = _QueuedConversation(
        token="newer-token",
        key=f"newer:{session_id}",
        namespace="newer",
        event_session_id=session_id,
        owner_user_id=event.user_id,
        state={},
        reply_check=choice_check,
        group_reply_check=None,
        handlers=[],
    )
    manager._queued_by_token[older.token] = older
    manager._queued_by_token[newer.token] = newer

    assert manager.matching_queued_conversation(event) is newer
