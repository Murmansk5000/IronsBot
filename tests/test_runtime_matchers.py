from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from nonebot.adapters import Event  # noqa: TC002 - the signature test resolves it
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.dependencies.utils import get_typed_signature
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher, current_event
from nonebot.rule import Rule
from nonebot.typing import T_State
from nonebot.utils import is_coroutine_callable

from ironsbot.config.models.messaging import CommandCooldownConfig
from ironsbot.core.request_coordination import RequestCoordinator
from ironsbot.runtime.matchers import (
    QUEUED_CONVERSATION_EXIT_PRIORITY,
    QUEUED_CONVERSATION_INPUT_PRIORITY,
    QUEUED_CONVERSATION_RESERVATION_PRIORITY,
    QUEUED_CONVERSATION_TICKET_STATE_KEY,
    QUEUED_CONVERSATION_TOKEN_STATE_KEY,
    RUNTIME_CONTEXT_TOKEN_STATE_KEY,
    TEMP_MATCHER_STATE_TOKEN_KEY,
    MatcherRegistry,
    PromptSessionManager,
    _capture_queued_conversation_input,
    _matches_active_queued_conversation,
    _matches_active_queued_conversation_exit,
    _restore_temporary_matcher_state,
    begin_queued_conversation,
    bind,
    bind_async,
    get_prompt_session_manager,
)
from ironsbot.runtime.prompt_sessions import (
    QUEUED_CONVERSATION_KEEP_OPEN_STATE_KEY,
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


@pytest.mark.asyncio
async def test_parallel_queued_conversation_reserves_fifo_tickets_without_waiting(
) -> None:
    second_ticket_number = 2
    manager = PromptSessionManager()
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id="group_1_2",
        state={},
        reply_check=lambda _event: True,
        handlers=[],
        parallel=True,
    )

    first_ticket = await context.acquire()
    assert first_ticket == 1
    context.mark_dispatched(first_ticket)
    second_ticket = await asyncio.wait_for(context.acquire(), timeout=0.1)
    assert second_ticket == second_ticket_number
    context.mark_dispatched(second_ticket)

    context.complete(2)
    context.complete(1)


def test_queued_conversation_claims_each_onebot_message_once() -> None:
    manager = PromptSessionManager()
    event = group_message_event("1", message_id=42)

    assert manager.claim_input(event)
    assert not manager.claim_input(event)
    assert manager.claim_input(group_message_event("2", message_id=43))
    assert manager.claim_input(
        group_message_event("1", self_id=2, message_id=42)
    )


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


def test_group_menu_reply_accepts_napcat_reply_segment_without_metadata() -> None:
    anchor = GroupMenuAnchor(group_id=4, bot_user_id=1, message_id=99)
    message = Message(
        [MessageSegment.reply(99), MessageSegment.at(1), MessageSegment.text("3")]
    )
    event = group_message_event(
        "3",
        user_id=3,
        group_id=4,
        self_id=1,
        message=message,
        raw_message="[reply:id=99][at:qq=1]3",
    )

    assert event.reply is None
    assert is_current_group_menu_reply(event, anchor)


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


def test_group_menu_reply_zero_is_silent_even_when_exit_was_legacy_enabled() -> None:
    manager = PromptSessionManager()
    owner = group_message_event("1", user_id=2, group_id=4, self_id=1)
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id=owner.get_session_id(),
        owner_user_id=owner.user_id,
        state={"owner": owner.user_id},
        reply_check=lambda event: event.get_session_id() == owner.get_session_id(),
        group_reply_check=lambda event: event.get_plaintext().strip() in {"1", "0"},
        handlers=[],
        menu_anchor=GroupMenuAnchor(group_id=4, bot_user_id=1, message_id=99),
        allow_group_reply_exit=True,
    )
    member_exit = group_message_event(
        "0",
        user_id=3,
        group_id=4,
        self_id=1,
        message_id=100,
        reply_sender_user_id=1,
    )

    assert not context.matches(member_exit)
    assert not context.is_shared_group_reply(member_exit)


def test_stable_menu_router_keeps_third_party_reply_support() -> None:
    manager = PromptSessionManager()
    registry = MatcherRegistry(
        cooldown=cast("CommandCooldown", object()),
        priorities=object(),
        prompt_session_manager=manager,
    )
    state = registry._with_runtime_hooks({})["state"]
    owner = group_message_event("1", user_id=2, group_id=4, self_id=1)
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id=owner.get_session_id(),
        owner_user_id=owner.user_id,
        state={},
        reply_check=lambda event: event.get_session_id() == owner.get_session_id()
        and event.get_plaintext().strip() == "1",
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

    assert _matches_active_queued_conversation(member_choice, state)
    assert state[QUEUED_CONVERSATION_TOKEN_STATE_KEY] == context.token
    assert not _matches_active_queued_conversation(member_exit, state)


def test_numeric_selection_prompt_accepts_owner_bot_mention_or_plain_choice() -> None:
    manager = PromptSessionManager()
    owner = group_message_event("魂帝技能", user_id=2, group_id=4, self_id=1)
    context = manager.start_queued_conversation(
        namespace="selection_prompt",
        event_session_id=owner.get_session_id(),
        owner_user_id=owner.user_id,
        state={},
        reply_check=lambda event: event.get_session_id() == owner.get_session_id()
        and event.get_plaintext().strip().isdigit(),
        handlers=[],
    )
    mentioned_choice = group_message_event(
        user_id=owner.user_id,
        group_id=4,
        self_id=1,
        message=Message([MessageSegment.at(1), MessageSegment.text(" 2")]),
        raw_message="[CQ:at,qq=1] 2",
    )
    plain_choice = group_message_event(
        "2",
        user_id=owner.user_id,
        group_id=4,
        self_id=1,
    )

    assert context.matches(mentioned_choice)
    assert context.matches(plain_choice)


def test_queued_menu_uses_singleton_permanent_routers() -> None:
    manager = PromptSessionManager()
    registry = MatcherRegistry(
        cooldown=cast("CommandCooldown", object()),
        priorities=object(),
        prompt_session_manager=manager,
    )

    registry.install_queued_conversation_router()
    registry.install_queued_conversation_router()

    assert len(registry.message_matchers) == len(
        (QUEUED_CONVERSATION_EXIT_PRIORITY, QUEUED_CONVERSATION_INPUT_PRIORITY)
    )
    exit_router, input_router = registry.message_matchers
    assert exit_router.priority == QUEUED_CONVERSATION_EXIT_PRIORITY
    assert input_router.priority == QUEUED_CONVERSATION_INPUT_PRIORITY
    assert not exit_router.temp
    assert not input_router.temp
    assert QUEUED_CONVERSATION_INPUT_PRIORITY < QUEUED_CONVERSATION_RESERVATION_PRIORITY


def test_queued_menu_exit_has_a_dedicated_earlier_route() -> None:
    manager = PromptSessionManager()
    registry = MatcherRegistry(
        cooldown=cast("CommandCooldown", object()),
        priorities=object(),
        prompt_session_manager=manager,
    )
    state = registry._with_runtime_hooks({})["state"]
    origin = group_message_event("米米号1", user_id=2, group_id=4, self_id=1)
    context = manager.start_queued_conversation(
        namespace="player_detail",
        event_session_id=origin.get_session_id(),
        owner_user_id=origin.user_id,
        state={},
        reply_check=lambda event: event.get_session_id() == origin.get_session_id()
        and event.get_plaintext().strip() in {"0", "1", "2", "3"},
        handlers=[],
        parallel=True,
    )
    exit_event = group_message_event(
        "0",
        user_id=2,
        group_id=4,
        self_id=1,
        message_id=10,
    )
    choice_event = group_message_event(
        "3",
        user_id=2,
        group_id=4,
        self_id=1,
        message_id=11,
    )

    assert _matches_active_queued_conversation_exit(exit_event, state)
    assert state[QUEUED_CONVERSATION_TOKEN_STATE_KEY] == context.token
    state.pop(QUEUED_CONVERSATION_TOKEN_STATE_KEY)
    assert not _matches_active_queued_conversation_exit(choice_event, state)
    assert _matches_active_queued_conversation(choice_event, state)


@pytest.mark.asyncio
async def test_permanent_router_accepts_parallel_choices_before_exit() -> None:
    class _Features:
        @staticmethod
        def is_superuser(user_id: int) -> bool:
            _ = user_id
            return False

    class _DuplicateConfig:
        duplicate_window_seconds = 60.0
        duplicate_message = "该指令正在查询中，请勿重复发送。"

    class _MatcherProbe:
        def __init__(self, state: T_State) -> None:
            self.state = state
            self.remain_handlers: list[Any] = []
            self.messages: list[str] = []

        async def send(self, message: object) -> None:
            self.messages.append(str(message))

        async def finish(self, message: object) -> None:
            self.messages.append(str(message))
            raise FinishedException

    manager = PromptSessionManager()
    coordinator = RequestCoordinator(_Features(), _DuplicateConfig())
    registry = MatcherRegistry(
        cooldown=cast("CommandCooldown", object()),
        priorities=object(),
        prompt_session_manager=manager,
        request_coordinator=coordinator,
    )
    origin = group_message_event("米米号1", user_id=2, group_id=4, self_id=1)
    context = manager.start_queued_conversation(
        namespace="player_detail",
        event_session_id=origin.get_session_id(),
        owner_user_id=origin.user_id,
        state={},
        reply_check=lambda event: event.get_session_id() == origin.get_session_id()
        and event.get_plaintext().strip() in {"0", "1", "2", "3"},
        handlers=[],
        parallel=True,
        semantic_request_resolver=lambda event, _state: _semantic_request(
            event.get_plaintext().strip()
        ),
        request_coordinator=coordinator,
    )

    async def dispatch(message_id: int, choice: str) -> str:
        event = group_message_event(
            choice,
            user_id=2,
            group_id=4,
            self_id=1,
            message_id=message_id,
        )
        state = registry._with_runtime_hooks({})["state"]
        assert _matches_active_queued_conversation(event, state)
        matcher = _MatcherProbe(state)
        await _capture_queued_conversation_input(
            cast("Matcher", matcher),
            event,
            state,
        )
        token = state["_ironsbot_request_response_token"]
        return token.request.target.key

    dispatched = await asyncio.gather(
        dispatch(10, "1"),
        dispatch(11, "2"),
        dispatch(12, "3"),
    )
    assert dispatched == ["1", "2", "3"]
    assert context.active_ticket_count == len(dispatched)

    exit_event = group_message_event(
        "0",
        user_id=2,
        group_id=4,
        self_id=1,
        message_id=13,
    )
    exit_state = registry._with_runtime_hooks({})["state"]
    assert _matches_active_queued_conversation_exit(exit_event, exit_state)
    exit_matcher = _MatcherProbe(exit_state)
    with pytest.raises(FinishedException):
        await _capture_queued_conversation_input(
            cast("Matcher", exit_matcher),
            exit_event,
            exit_state,
        )

    assert not context.active
    assert exit_matcher.messages == ["[CQ:at,qq=2] 已退出当前选择。"]


def test_queued_conversation_activation_replaces_handlers_and_parallel_mode() -> None:
    manager = PromptSessionManager()
    first_handler = object()
    second_handler = object()
    context = manager.start_queued_conversation(
        namespace="player_detail",
        event_session_id="private_2",
        state={"stage": "detail"},
        reply_check=lambda _event: True,
        handlers=[first_handler],
        parallel=True,
    )

    manager.activate_queued_conversation(
        context,
        state={"stage": "binding"},
        reply_check=lambda _event: True,
        group_reply_check=None,
        menu_anchor=None,
        allow_group_reply_exit=False,
        semantic_request_resolver=None,
        handlers=[second_handler],
        parallel=False,
        page_id="player:binding",
        menu_sent=False,
    )

    assert context.handlers == [second_handler]
    assert not context.parallel
    assert context.state == {"stage": "binding"}


@pytest.mark.asyncio
async def test_queued_menu_page_changes_extend_the_root_deadline_with_a_cap() -> None:
    manager = PromptSessionManager(
        root_timeout_seconds=180,
        page_extension_seconds=60,
        max_timeout_seconds=300,
    )
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id="private_2",
        state={},
        reply_check=lambda _event: True,
        handlers=[],
    )

    manager.record_menu_page(context, page_id="root")
    assert context.root_menu_opened_at is not None
    assert context.deadline == pytest.approx(context.root_menu_opened_at + 180)

    manager.record_menu_page(context, page_id="root")
    assert context.deadline == pytest.approx(context.root_menu_opened_at + 180)

    manager.record_menu_page(context, page_id="detail")
    assert context.deadline == pytest.approx(context.root_menu_opened_at + 240)

    manager.record_menu_page(context, page_id="return")
    assert context.deadline == pytest.approx(context.root_menu_opened_at + 300)

    manager.record_menu_page(context, page_id="another")
    assert context.deadline == pytest.approx(context.root_menu_opened_at + 300)
    manager.cancel_queued_context(context)


@pytest.mark.asyncio
async def test_detaching_a_shared_reply_keeps_the_owner_conversation_active() -> None:
    expected_next_ticket = 2
    manager = PromptSessionManager()
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id="group_4_user_2",
        owner_user_id=2,
        state={"owner": 2},
        reply_check=lambda _event: True,
        handlers=[],
    )
    ticket = await context.acquire()
    assert ticket == 1
    state: T_State = {
        QUEUED_CONVERSATION_TOKEN_STATE_KEY: context.token,
        QUEUED_CONVERSATION_TICKET_STATE_KEY: ticket,
    }

    detached = manager.detach_queued_conversation(state)

    assert detached is context
    assert context.active
    assert state == {}
    next_ticket = await context.acquire()
    assert next_ticket == expected_next_ticket
    context.complete(next_ticket)


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
async def test_parallel_cancellation_suppresses_every_active_ticket() -> None:
    second_ticket_number = 2
    manager = PromptSessionManager()
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id="group_1_2",
        state={},
        reply_check=lambda _event: True,
        handlers=[],
        parallel=True,
    )
    first_ticket = await context.acquire()
    assert first_ticket == 1
    context.mark_dispatched(first_ticket)
    second_ticket = await context.acquire()
    assert second_ticket == second_ticket_number
    context.mark_dispatched(second_ticket)
    probe: T_State = {QUEUED_CONVERSATION_TOKEN_STATE_KEY: context.token}

    manager.cancel_queued_conversation(probe)
    assert manager.queued_conversation_is_cancelled(probe)

    manager.finish_queued_conversation(
        {
            QUEUED_CONVERSATION_TOKEN_STATE_KEY: context.token,
            QUEUED_CONVERSATION_TICKET_STATE_KEY: first_ticket,
        }
    )
    assert manager.queued_conversation_is_cancelled(probe)

    manager.finish_queued_conversation(
        {
            QUEUED_CONVERSATION_TOKEN_STATE_KEY: context.token,
            QUEUED_CONVERSATION_TICKET_STATE_KEY: second_ticket,
        }
    )
    assert not manager.queued_conversation_is_cancelled(probe)


@pytest.mark.asyncio
async def test_queued_conversation_releases_cancelled_pending_reservations() -> None:
    class Features:
        def is_superuser(self, user_id: int) -> bool:
            del user_id
            return False

    requests = RequestCoordinator(Features(), CommandCooldownConfig())
    manager = PromptSessionManager()
    context = manager.start_queued_conversation(
        namespace="test",
        event_session_id="group_1_2",
        state={},
        reply_check=lambda _event: True,
        handlers=[],
        request_coordinator=requests,
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


@pytest.mark.asyncio
async def test_pending_conversation_holds_early_menu_input_until_activation() -> None:
    manager = PromptSessionManager()
    owner = private_message_event("米米号105023264", user_id=2, self_id=1)
    context = manager.start_queued_conversation(
        namespace="player_detail",
        event_session_id=owner.get_session_id(),
        owner_user_id=owner.user_id,
        state={"player_id": 105_023_264},
        reply_check=lambda event: event.get_plaintext().strip() in {"1", "2"},
        pending_reply_check=lambda event: event.get_session_id()
        == owner.get_session_id()
        and event.get_plaintext().strip().isdigit(),
        handlers=[],
        pending=True,
        parallel=True,
    )
    early_selection = private_message_event("2", user_id=2, self_id=1)

    assert context.matches(early_selection)
    reservation = context.reserve()
    assert reservation is not None
    ticket, ready = reservation
    await ready
    activation = asyncio.create_task(context.wait_until_active())
    await asyncio.sleep(0)

    assert not activation.done()
    context.activate(
        state={"player_id": 105_023_264, "choices": ("1", "2")},
        reply_check=lambda event: event.get_plaintext().strip() in {"1", "2"},
        group_reply_check=None,
        menu_anchor=None,
        allow_group_reply_exit=False,
        semantic_request_resolver=None,
    )

    assert await activation
    assert context.state == {"player_id": 105_023_264, "choices": ("1", "2")}
    context.complete(ticket)


@pytest.mark.asyncio
async def test_player_command_attaches_the_high_priority_pending_reservation() -> None:
    manager = PromptSessionManager()
    registry = MatcherRegistry(
        cooldown=cast("CommandCooldown", object()),
        priorities=object(),
        prompt_session_manager=manager,
    )
    event = private_message_event("米米号", user_id=2, self_id=1)
    context = manager.start_queued_conversation(
        namespace="seer_player",
        event_session_id=event.get_session_id(),
        owner_user_id=event.user_id,
        state={},
        reply_check=lambda _event: True,
        pending_reply_check=lambda _event: True,
        handlers=[],
        pending=True,
        parallel=True,
    )
    state = registry._with_runtime_hooks({})["state"]
    matcher = cast("Matcher", SimpleNamespace(state=state))
    event_token = current_event.set(event)
    try:
        await begin_queued_conversation(
            matcher,
            [],
            namespace="seer_player",
            pending_reply_check=lambda _event: True,
            queue_reply_check=lambda _event: True,
            queue_parallel=True,
        )
    finally:
        current_event.reset(event_token)

    assert state[QUEUED_CONVERSATION_TOKEN_STATE_KEY] == context.token
    assert manager.queued_conversation_for(
        namespace="seer_player",
        event_session_id=event.get_session_id(),
    ) is context


@pytest.mark.asyncio
async def test_pending_player_reservation_accepts_rapid_1_2_3_4_before_menu() -> None:
    manager = PromptSessionManager()
    registry = MatcherRegistry(
        cooldown=cast("CommandCooldown", object()),
        priorities=object(),
        prompt_session_manager=manager,
    )
    owner = private_message_event("米米号", user_id=2, self_id=1)
    context = manager.start_queued_conversation(
        namespace="seer_player",
        event_session_id=owner.get_session_id(),
        owner_user_id=owner.user_id,
        state={},
        reply_check=lambda event: event.get_plaintext().strip() in {"1", "2", "3", "4"},
        pending_reply_check=lambda event: event.get_session_id()
        == owner.get_session_id()
        and event.get_plaintext().strip().isdigit(),
        handlers=[],
        pending=True,
        parallel=True,
    )

    async def dispatch(message_id: int, choice: str) -> int:
        event = private_message_event(
            choice,
            user_id=owner.user_id,
            self_id=owner.self_id,
            message_id=message_id,
        )
        state = registry._with_runtime_hooks({})["state"]
        assert _matches_active_queued_conversation(event, state)
        matcher = cast(
            "Matcher",
            SimpleNamespace(state=state, remain_handlers=[]),
        )
        await _capture_queued_conversation_input(matcher, event, state)
        return cast("int", state[QUEUED_CONVERSATION_TICKET_STATE_KEY])

    choices = ("1", "2", "3", "4")
    tasks = [
        asyncio.create_task(dispatch(message_id, choice))
        for message_id, choice in enumerate(choices, start=10)
    ]
    await asyncio.sleep(0)
    assert not any(task.done() for task in tasks)

    context.activate(
        state={"player_id": 148_758_762},
        reply_check=lambda event: event.get_plaintext().strip()
        in {"1", "2", "3", "4"},
        group_reply_check=None,
        menu_anchor=None,
        allow_group_reply_exit=False,
        semantic_request_resolver=None,
    )

    assert await asyncio.gather(*tasks) == [1, 2, 3, 4]
    assert context.active_ticket_count == len(choices)
    for ticket in range(1, len(choices) + 1):
        context.complete(ticket)


def test_pending_reservation_survives_its_early_matcher_completion() -> None:
    manager = PromptSessionManager()
    context = manager.start_queued_conversation(
        namespace="seer_player",
        event_session_id="private_2",
        state={},
        reply_check=lambda _event: True,
        pending_reply_check=lambda _event: True,
        handlers=[],
        pending=True,
    )
    state: T_State = {
        QUEUED_CONVERSATION_TOKEN_STATE_KEY: context.token,
        QUEUED_CONVERSATION_KEEP_OPEN_STATE_KEY: True,
    }

    manager.finish_queued_conversation(state)

    assert context.active
    assert context.pending
    assert manager.queued_conversation_for(
        namespace="seer_player",
        event_session_id="private_2",
    ) is context


@pytest.mark.asyncio
async def test_unactivated_conversation_cancels_after_first_level_command() -> None:
    manager = PromptSessionManager()
    context = manager.start_queued_conversation(
        namespace="player_detail",
        event_session_id="private_2",
        state={},
        reply_check=lambda _event: True,
        pending_reply_check=lambda _event: True,
        handlers=[],
        pending=True,
    )
    state: T_State = {QUEUED_CONVERSATION_TOKEN_STATE_KEY: context.token}
    waiting = asyncio.create_task(context.wait_until_active())
    await asyncio.sleep(0)

    manager.finish_queued_conversation(state)

    assert not await waiting
    assert not context.active
