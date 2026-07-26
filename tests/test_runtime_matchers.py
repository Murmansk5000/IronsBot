from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy
from datetime import timedelta
from typing import TYPE_CHECKING, cast

import pytest
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.utils import is_coroutine_callable

from ironsbot.runtime.matchers import (
    TEMP_MATCHER_STATE_TOKEN_KEY,
    PromptSessionManager,
    _restore_temporary_matcher_state,
    bind_async,
)

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.typing import T_State


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
