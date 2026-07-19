from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, cast

import pytest
from nonebot.rule import Rule
from nonebot.utils import is_coroutine_callable

from ironsbot.runtime.matchers import bind_async

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
