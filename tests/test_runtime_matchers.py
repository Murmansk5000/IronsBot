from __future__ import annotations

import inspect
from typing import cast

import pytest
from nonebot.adapters import Event  # noqa: TC002 - the signature test resolves it
from nonebot.dependencies.utils import get_typed_signature
from nonebot.rule import Rule
from nonebot.typing import T_State
from nonebot.utils import is_coroutine_callable

from ironsbot.core.action_categories import RequestCategory
from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)
from ironsbot.integrations.onebot.matcher_support import bind, bind_async


def _semantic_request(target: str) -> SemanticRequest:
    return SemanticRequest(
        action=ActionDefinition(
            "selection", "选择", category=RequestCategory.OTHER_NETWORK
        ),
        target=SemanticTarget(target, target),
        source=SemanticRequestSource.MENU,
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
