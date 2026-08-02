from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy
from datetime import timedelta
from typing import TYPE_CHECKING, cast

import pytest
from nonebot.adapters import Event  # noqa: TC002 - the signature test resolves it
from nonebot.dependencies.utils import get_typed_signature
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State
from nonebot.utils import is_coroutine_callable

from ironsbot.config.models.messaging import CommandCooldownConfig
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.runtime.matchers import (
    QUEUED_CONVERSATION_TICKET_STATE_KEY,
    QUEUED_CONVERSATION_TOKEN_STATE_KEY,
    RUNTIME_CONTEXT_TOKEN_STATE_KEY,
    TEMP_MATCHER_STATE_TOKEN_KEY,
    MatcherRegistry,
    PromptSessionManager,
    _restore_temporary_matcher_state,
    bind,
    bind_async,
    get_prompt_session_manager,
)
from ironsbot.runtime.prompt_sessions import (
    GroupMenuAnchor,
    is_current_group_menu_reply,
)
from ironsbot.runtime.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)
from tests.helpers.onebot_events import group_message_event, private_message_event

if TYPE_CHECKING:
    from ironsbot.runtime.matcher_contracts import CommandCooldown


def _semantic_request(target: str) -> SemanticRequest:
    return SemanticRequest(
        action=ActionDefinition("selection", "选择"),
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


@pytest.mark.asyncio
async def test_matcher_runtime_context_keeps_live_tasks_out_of_matcher_state() -> None:
    manager = PromptSessionManager()
    completed = asyncio.Event()
    task = asyncio.create_task(completed.wait())

    try:
        registry = MatcherRegistry(
            cooldown=cast("CommandCooldown", object()),
            priorities=object(),
            prompt_session_manager=manager,
        )
        state = registry._with_runtime_hooks({})["state"]

        assert set(state) == {RUNTIME_CONTEXT_TOKEN_STATE_KEY}
        assert isinstance(state[RUNTIME_CONTEXT_TOKEN_STATE_KEY], str)
        assert deepcopy(state) == state
        assert get_prompt_session_manager(state) is manager
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


def test_group_menu_reply_accepts_only_the_current_bot_menu() -> None:
    manager = PromptSessionManager()
    anchor = GroupMenuAnchor(group_id=4, bot_user_id=1, message_id=99)
    owner = group_message_event("a", user_id=2, group_id=4, self_id=1)
    member_reply = group_message_event(
        "A",
        user_id=3,
        group_id=4,
        self_id=1,
        message_id=100,
        reply_sender_user_id=1,
    )
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id=owner.get_session_id(),
        owner_user_id=owner.user_id,
        state={},
        reply_check=lambda event: event.get_session_id() == owner.get_session_id()
        and getattr(event, "reply", None) is None
        and event.get_plaintext().strip().lower() == "a",
        group_reply_check=lambda event: event.get_plaintext().strip().lower() == "a",
        handlers=[],
        menu_anchor=anchor,
    )

    assert is_current_group_menu_reply(member_reply, anchor)
    assert context.matches(owner)
    assert context.matches(member_reply)
    assert not context.matches(group_message_event("a", user_id=3, group_id=4))
    assert not context.matches(
        group_message_event(
            "a",
            user_id=3,
            group_id=4,
            message_id=99,
            reply_sender_user_id=1,
        )
    )
    assert not context.matches(private_message_event("a", user_id=3))


def test_group_menu_reply_cannot_exit_the_owner_conversation() -> None:
    manager = PromptSessionManager()
    owner = group_message_event("1", user_id=2, group_id=4, self_id=1)
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id=owner.get_session_id(),
        owner_user_id=owner.user_id,
        state={},
        reply_check=lambda event: event.get_session_id() == owner.get_session_id()
        and getattr(event, "reply", None) is None
        and event.get_plaintext().strip() in {"1", "0"},
        group_reply_check=lambda event: event.get_plaintext().strip() in {"1", "0"},
        handlers=[],
        menu_anchor=GroupMenuAnchor(group_id=4, bot_user_id=1, message_id=99),
    )
    member_choice = group_message_event(
        "1",
        user_id=3,
        group_id=4,
        self_id=1,
        message_id=100,
        reply_sender_user_id=1,
    )
    member_exit = group_message_event(
        "0",
        user_id=3,
        group_id=4,
        self_id=1,
        message_id=100,
        reply_sender_user_id=1,
    )
    owner_exit = group_message_event(
        "0",
        user_id=2,
        group_id=4,
        self_id=1,
        message_id=100,
        reply_sender_user_id=1,
    )
    owner_direct_exit = group_message_event(
        "0",
        user_id=2,
        group_id=4,
        self_id=1,
    )

    assert context.matches(member_choice)
    assert not context.matches(member_exit)
    assert context.matches(owner_exit)
    assert context.matches(owner_direct_exit)


def test_group_menu_reply_uses_only_the_latest_menu_anchor() -> None:
    manager = PromptSessionManager()
    owner = group_message_event("a", user_id=2, group_id=4, self_id=1)
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id=owner.get_session_id(),
        state={},
        reply_check=lambda event: event.get_session_id() == owner.get_session_id()
        and getattr(event, "reply", None) is None
        and event.get_plaintext().strip().lower() == "a",
        group_reply_check=lambda event: event.get_plaintext().strip().lower() == "a",
        handlers=[],
        menu_anchor=GroupMenuAnchor(group_id=4, bot_user_id=1, message_id=99),
    )
    old_reply = group_message_event(
        "a",
        user_id=3,
        group_id=4,
        message_id=100,
        reply_sender_user_id=1,
    )
    assert context.matches(old_reply)

    context.update_menu_anchor(
        GroupMenuAnchor(group_id=4, bot_user_id=1, message_id=100)
    )

    assert not context.matches(old_reply)
    assert context.matches(
        group_message_event(
            "a",
            user_id=3,
            group_id=4,
            message_id=101,
            reply_sender_user_id=1,
        )
    )


def test_group_menu_reply_stays_closed_without_a_sent_menu_id() -> None:
    manager = PromptSessionManager()
    owner = group_message_event("1", user_id=2, group_id=4, self_id=1)
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id=owner.get_session_id(),
        state={},
        reply_check=lambda event: event.get_session_id() == owner.get_session_id(),
        group_reply_check=lambda event: event.get_plaintext().strip().isdigit(),
        handlers=[],
    )

    assert not context.matches(
        group_message_event(
            "1",
            user_id=3,
            group_id=4,
            message_id=100,
            reply_sender_user_id=1,
        )
    )


def test_group_menu_reply_rejects_another_group_or_bot_account() -> None:
    anchor = GroupMenuAnchor(group_id=4, bot_user_id=1, message_id=99)

    assert not is_current_group_menu_reply(
        group_message_event(
            "1",
            user_id=3,
            group_id=5,
            self_id=1,
            message_id=100,
            reply_sender_user_id=1,
        ),
        anchor,
    )
    assert not is_current_group_menu_reply(
        group_message_event(
            "1",
            user_id=3,
            group_id=4,
            self_id=2,
            message_id=100,
            reply_sender_user_id=1,
        ),
        anchor,
    )


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
async def test_queued_conversation_releases_cancelled_pending_reservations() -> None:
    class Features:
        def is_superuser(self, user_id: int) -> bool:
            del user_id
            return False

    requests = InFlightRequestService(Features(), CommandCooldownConfig())
    manager = PromptSessionManager()
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id="group_1_2",
        state={},
        reply_check=lambda _event: True,
        handlers=[],
        request_service=requests,
    )
    active = requests.admit(
        user_id=1,
        request=_semantic_request("1"),
    )
    pending = requests.admit(
        user_id=1,
        request=_semantic_request("2"),
    )
    assert active.token is not None
    assert pending.token is not None

    active_ticket = await context.acquire(active.token)
    assert active_ticket is not None
    waiting = asyncio.create_task(context.acquire(pending.token))
    await asyncio.sleep(0)
    manager.cancel_queued_conversation(
        {QUEUED_CONVERSATION_TOKEN_STATE_KEY: context.token}
    )

    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert requests.admit(
        user_id=1,
        request=_semantic_request("2"),
    ).allowed
    assert not requests.admit(
        user_id=1,
        request=_semantic_request("1"),
    ).allowed

    context.complete(active_ticket)
    requests.finish(active.token)


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
