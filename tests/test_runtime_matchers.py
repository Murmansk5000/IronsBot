from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy
from datetime import timedelta
from typing import cast

import pytest
from nonebot.adapters import Event  # noqa: TC002 - the signature test resolves it
from nonebot.dependencies.utils import get_typed_signature
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State
from nonebot.utils import is_coroutine_callable

from ironsbot.runtime.matchers import (
    QUEUED_CONVERSATION_TICKET_STATE_KEY,
    QUEUED_CONVERSATION_TOKEN_STATE_KEY,
    RUNTIME_CONTEXT_TOKEN_STATE_KEY,
    TEMP_MATCHER_STATE_TOKEN_KEY,
    CommandCooldown,
    MatcherRegistry,
    PromptSessionManager,
    _restore_temporary_matcher_state,
    bind,
    bind_async,
    get_prompt_session_manager,
    get_reply_before_send,
)


async def _bound_checker(
    prefix: str,
    event: Event,
    state: T_State,
) -> bool:
    state["value"] = prefix
    return event is not None


@pytest.mark.asyncio
async def test_bind_async_preserves_signature_and_coroutine_identity() -> None:
    checker = bind_async(_bound_checker, "ready")

    assert is_coroutine_callable(checker)
    assert tuple(inspect.signature(checker).parameters) == ("event", "state")

    state: T_State = {}
    assert await checker(cast("Event", object()), state)
    assert state == {"value": "ready"}

    dependency = next(iter(Rule(checker).checkers))
    assert is_coroutine_callable(dependency.call)
    assert get_typed_signature(checker).parameters["state"].annotation is T_State


def test_bind_hides_application_supplied_keyword_arguments() -> None:
    def checker(event: Event, *, service: object) -> bool:
        return event is not None and service is not None

    bound = bind(checker, service=object())

    assert tuple(inspect.signature(bound).parameters) == ("event",)
    assert tuple(get_typed_signature(bound).parameters) == ("event",)


@pytest.mark.asyncio
async def test_matcher_runtime_context_keeps_live_tasks_out_of_matcher_state() -> None:
    manager = PromptSessionManager()
    completed = asyncio.Event()
    task = asyncio.create_task(completed.wait())

    class ReplyCoordinator:
        def __init__(self) -> None:
            self.task = task

        async def before_send(self, _event: Event | None) -> None:
            return None

    coordinator = ReplyCoordinator()

    try:
        registry = MatcherRegistry(
            cooldown=cast("CommandCooldown", object()),
            priorities=object(),
            before_reply_send=coordinator.before_send,
            prompt_session_manager=manager,
        )
        state = registry._with_runtime_hooks({})["state"]

        assert set(state) == {RUNTIME_CONTEXT_TOKEN_STATE_KEY}
        assert isinstance(state[RUNTIME_CONTEXT_TOKEN_STATE_KEY], str)
        assert deepcopy(state) == state
        assert get_prompt_session_manager(state) is manager
        assert get_reply_before_send(state) is not None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_temporary_matcher_state_keeps_tasks_out_of_default_state() -> None:
    wait_for_completion = asyncio.Event()
    task = asyncio.create_task(wait_for_completion.wait())
    token = PromptSessionManager.store_temporary_matcher_state(
        {"task": task, "persisted": "value"},
        expires_after=timedelta(minutes=1),
    )
    temporary = Matcher.new(
        "message",
        Rule(),
        handlers=[_restore_temporary_matcher_state],
        temp=True,
        default_state={TEMP_MATCHER_STATE_TOKEN_KEY: token},
    )

    try:
        assert deepcopy(temporary._default_state) == {
            TEMP_MATCHER_STATE_TOKEN_KEY: token,
        }

        matcher = temporary()
        matcher.state["incoming"] = "event"
        await _restore_temporary_matcher_state(matcher.state)

        assert matcher.state["task"] is task
        assert matcher.state["persisted"] == "value"
        assert matcher.state["incoming"] == "event"
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        temporary.destroy()


@pytest.mark.asyncio
async def test_queued_conversation_serializes_inputs_in_arrival_order() -> None:
    second_ticket_number = 2
    manager = PromptSessionManager()
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id="group_1_2",
        state={"saved": "value"},
        reply_check=lambda _event: True,
        handlers=[],
    )

    first_ticket = await context.acquire()
    second = asyncio.create_task(context.acquire())
    await asyncio.sleep(0)

    assert first_ticket == 1
    assert not second.done()

    context.complete(first_ticket)
    second_ticket = await second

    assert second_ticket == second_ticket_number
    context.complete(second_ticket)


@pytest.mark.asyncio
async def test_queued_conversation_cancellation_drops_pending_inputs() -> None:
    manager = PromptSessionManager()
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id="group_1_2",
        state={},
        reply_check=lambda _event: True,
        handlers=[],
    )
    state: T_State = {
        QUEUED_CONVERSATION_TOKEN_STATE_KEY: context.token,
    }
    first_ticket = await context.acquire()
    pending = asyncio.create_task(context.acquire())
    await asyncio.sleep(0)

    manager.cancel_queued_conversation(state)

    assert manager.queued_conversation(state) is None
    assert manager.queued_conversation_is_cancelled(state)
    with pytest.raises(asyncio.CancelledError):
        await pending

    state[QUEUED_CONVERSATION_TICKET_STATE_KEY] = first_ticket
    manager.finish_queued_conversation(state)
    assert not manager.queued_conversation_is_cancelled(state)


@pytest.mark.asyncio
async def test_queued_conversation_expiry_suppresses_active_reply() -> None:
    manager = PromptSessionManager()
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id="group_1_2",
        state={},
        reply_check=lambda _event: True,
        handlers=[],
    )
    state: T_State = {
        QUEUED_CONVERSATION_TOKEN_STATE_KEY: context.token,
    }
    ticket = await context.acquire()

    manager._expire_queued_conversation(context.token)

    assert manager.queued_conversation(state) is None
    assert manager.queued_conversation_is_cancelled(state)

    state[QUEUED_CONVERSATION_TICKET_STATE_KEY] = ticket
    manager.finish_queued_conversation(state)
    assert not manager.queued_conversation_is_cancelled(state)
