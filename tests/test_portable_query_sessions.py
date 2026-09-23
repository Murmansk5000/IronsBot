from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, SendResult, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    singleton_target,
)
from ironsbot.services.portable_query_operations import build_query_operation
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessionError,
    PortableQuerySessions,
    PortableTextInputSpec,
    QueryOperationSpec,
)
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.query_result import QueryChoice, QueryReply, QueryResult


def test_portable_menu_rejects_mismatched_labels() -> None:
    with pytest.raises(PortableQuerySessionError, match="labels"):
        PortableMenuSpec(
            choices=("one", "two"),
            select=AsyncMock(),
            prompt=OutboundMessage.from_text("choose"),
            labels=("one",),
        )


def test_portable_menu_rejects_mismatched_text_inputs() -> None:
    with pytest.raises(ValueError, match="text inputs"):
        PortableMenuSpec(
            choices=("one", "two"),
            select=AsyncMock(),
            prompt=OutboundMessage.from_text("choose"),
            text_inputs=(frozenset({"one"}),),
        )


@pytest.mark.parametrize(
    "choice_keys",
    [
        ("11",),
        ("", "12"),
        ("0", "12"),
        ("11", "11"),
    ],
)
def test_portable_menu_rejects_invalid_explicit_choice_keys(
    choice_keys: tuple[str, ...],
) -> None:
    with pytest.raises(PortableQuerySessionError, match="choice keys"):
        PortableMenuSpec(
            choices=("one", "two"),
            choice_keys=choice_keys,
            select=AsyncMock(),
            prompt=OutboundMessage.from_text("choose"),
        )


def test_portable_menu_rejects_unknown_shared_choice() -> None:
    with pytest.raises(PortableQuerySessionError, match="shared menu choices"):
        PortableMenuSpec(
            choices=("one",),
            select=AsyncMock(),
            prompt=OutboundMessage.from_text("choose"),
            shared_select=AsyncMock(),
            shared_choice_indexes=frozenset({2}),
        )


@pytest.mark.asyncio
async def test_menu_text_aliases_are_explicit_and_share_button_selection() -> None:
    sessions = PortableQuerySessions()
    context = _context("owner")
    select = AsyncMock(return_value=OutboundMessage.from_text("selected"))
    menu = sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=("one",),
            select=select,
            prompt=OutboundMessage.from_text("choose"),
            labels=("display label",),
            text_inputs=(frozenset({"accept", "是"}),),
            keep_open=True,
        ),
    )
    assert not sessions.recognizes_response("display label", context)
    await sessions.select(" ACCEPT ", context)
    await sessions.select("是", context)
    assert menu.prompt is not None
    await sessions.select(menu.prompt.action_data(menu.prompt.choices[0]), context)
    assert select.await_count == len(("accept", "是", "button"))
    for call in select.await_args_list:
        assert call.args == ("one", context)
    empty = sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=(),
            select=select,
            prompt=OutboundMessage.from_text("no choices"),
        ),
    )
    assert empty.prompt is None
    assert sessions.active_prompt(context) is None


@pytest.mark.asyncio
async def test_menu_explicit_keys_preserve_sparse_display_numbers() -> None:
    sessions = PortableQuerySessions()
    context = _context("owner")
    select = AsyncMock(
        side_effect=lambda value, _context: OutboundMessage.from_text(
            f"selected:{value}"
        )
    )
    menu = sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=("eleven", "twenty"),
            choice_keys=("11", "20"),
            select=select,
            prompt=OutboundMessage.from_text("rank page"),
            keep_open=True,
            claim_unknown_numeric=False,
        ),
    )

    assert menu.prompt is not None
    assert tuple(choice.id for choice in menu.prompt.choices) == ("11", "20", "0")
    assert not sessions.recognizes_response("1", context)
    assert sessions.recognizes_response("11", context)
    assert _text(await sessions.select("11", context)) == "selected:eleven"
    assert _text(await sessions.select("20", context)) == "selected:twenty"
    assert [call.args[0] for call in select.await_args_list] == ["eleven", "twenty"]


@pytest.mark.asyncio
async def test_reserved_response_waits_for_prompt_delivery() -> None:
    sessions = PortableQuerySessions()
    context = _context("member-openid")
    reservation = sessions.reserve_responses(
        context,
        lambda text: text.strip().isdigit(),
    )

    assert sessions.recognizes_response("1", context)
    waiting = asyncio.create_task(sessions.select("1", context))
    await asyncio.sleep(0)
    assert not waiting.done()

    async def select(
        value: str,
        _context: MessageInputContext,
    ) -> OutboundMessage:
        return OutboundMessage.from_text(f"selected:{value}")

    sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=("first",),
            select=select,
            prompt=OutboundMessage.from_text("choose"),
        ),
    )
    await asyncio.sleep(0)
    assert not waiting.done()

    reservation.release()

    assert _text(await waiting) == "selected:first"
    assert not sessions.has_active_session(context)


@pytest.mark.asyncio
async def test_cancelled_response_reservation_discards_unseen_prompt() -> None:
    sessions = PortableQuerySessions()
    context = _context("member-openid")
    reservation = sessions.reserve_responses(context, str.isdigit)
    waiting = asyncio.create_task(sessions.select("1", context))
    await asyncio.sleep(0)

    sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=("first",),
            select=AsyncMock(),
            prompt=OutboundMessage.from_text("choose"),
        ),
    )
    reservation.cancel()

    assert await waiting is None
    assert not sessions.has_active_session(context)
    assert not sessions.recognizes_response("1", context)


@pytest.mark.asyncio
async def test_reserved_response_expires_instead_of_waiting_forever() -> None:
    sessions = PortableQuerySessions(ttl_seconds=0.01)
    context = _context("member-openid")
    sessions.reserve_responses(context, str.isdigit)

    assert await sessions.select("1", context) is None
    assert not sessions.recognizes_response("1", context)


@dataclass(slots=True)
class _Clock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value


def _context(
    actor_id: str,
    *,
    group_id: str = "group-a",
    reply_to_id: str | None = None,
) -> MessageInputContext:
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        actor_id,
        "member",
        group_id,
    )
    conversation = ConversationRef(Platform.QQ_OFFICIAL, "group", group_id)
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=actor,
            conversation=conversation,
            message_id=f"message-{actor_id}-{group_id}",
            text="",
            reply_to_id=reply_to_id,
        ),
        mentions_bot=True,
    )


def _text(message: OutboundMessage | None) -> str:
    assert message is not None
    part = message.parts[0]
    assert isinstance(part, TextPart)
    return part.text


@pytest.mark.asyncio
async def test_empty_entity_result_is_silent_by_default() -> None:
    sessions = PortableQuerySessions()

    async def search(_argument: str) -> QueryResult[int]:
        return QueryResult()

    result = await sessions.begin(
        _context("member-openid"),
        argument="missing",
        spec=QueryOperationSpec(
            parser=lambda text: text,
            search=search,
            select=AsyncMock(),
            prompt_title="choose",
        ),
    )

    assert result is None


@pytest.mark.asyncio
async def test_selection_is_scoped_by_opaque_actor_and_conversation() -> None:
    sessions = PortableQuerySessions()

    async def search(_argument: str) -> QueryResult[int]:
        return QueryResult(
            choices=(
                QueryChoice("first", "101", 101),
                QueryChoice("second", "202", 202, is_sub_choice=True),
            )
        )

    async def select(value: int) -> QueryResult[object]:
        return QueryResult(reply=QueryReply(text=f"selected:{value}"))

    owner = _context("member-openid")
    other_member = _context("other-openid")
    other_group = _context("member-openid", group_id="group-b")
    result = await sessions.begin(
        owner,
        argument="query",
        spec=QueryOperationSpec(
            parser=lambda text: text,
            search=search,
            select=select,
            prompt_title="choose",
            not_found_message="missing",
        ),
    )

    assert "1. first（101）" in _text(result)
    assert " ↳ 2. second（202）" in _text(result)
    assert "\n   101" not in _text(result)
    assert sessions.recognizes_response("2", owner)
    assert not sessions.recognizes_response("2", other_member)
    assert not sessions.recognizes_response("2", other_group)
    assert "序号无效" in _text(await sessions.select("9", owner))
    assert sessions.recognizes_response("2", owner)
    assert _text(await sessions.select("2", owner)) == "selected:202"
    assert sessions.recognizes_response("1", owner)
    assert _text(await sessions.select("1", owner)) == "selected:101"
    assert _text(await sessions.select("0", owner)) == "已退出查询。"
    assert not sessions.recognizes_response("2", owner)


@pytest.mark.asyncio
async def test_query_selection_accepts_rapid_consecutive_choices() -> None:
    sessions = PortableQuerySessions()
    entered = asyncio.Event()

    async def search(_argument: str) -> QueryResult[int]:
        return QueryResult(
            choices=(
                QueryChoice("first", "", 1),
                QueryChoice("second", "", 2),
            )
        )

    async def select(value: int) -> QueryResult[object]:
        entered.set()
        await asyncio.sleep(0)
        return QueryResult(reply=QueryReply(text=f"selected:{value}"))

    context = _context("member-openid")
    await sessions.begin(
        context,
        argument="query",
        spec=QueryOperationSpec(
            parser=lambda text: text,
            search=search,
            select=select,
            prompt_title="choose",
        ),
    )

    first = asyncio.create_task(sessions.select("1", context))
    await entered.wait()
    second = asyncio.create_task(sessions.select("2", context))

    assert [_text(result) for result in await asyncio.gather(first, second)] == [
        "selected:1",
        "selected:2",
    ]
    assert sessions.has_active_session(context)


@pytest.mark.asyncio
async def test_shareable_group_choice_clones_session_for_quoted_responder() -> None:
    sessions = PortableQuerySessions()
    owner = _context("owner")
    responder = _context("responder", reply_to_id="current-menu")
    selected = AsyncMock(return_value=OutboundMessage.from_text("selected"))
    message = sessions.offer_menu(
        owner,
        PortableMenuSpec(
            choices=("read-only", "owner-only"),
            select=selected,
            prompt=OutboundMessage.from_text("menu"),
            shared_select=selected,
            shared_choice_indexes=frozenset({1}),
            keep_open=True,
        ),
    )

    sessions.record_delivery(
        owner, message, SendResult(delivered=True, message_id="current-menu")
    )
    assert sessions.recognizes_shared_response("1", owner, responder)
    assert not sessions.recognizes_shared_response("2", owner, responder)
    assert not sessions.recognizes_shared_response("1", owner, _context("responder"))
    assert not sessions.recognizes_shared_response(
        "1", owner, _context("responder", group_id="other", reply_to_id="menu")
    )

    result = await sessions.select_shared("1", owner, responder)

    assert isinstance(result, OutboundMessage)
    assert _text(result) == "selected"
    selected.assert_awaited_once_with("read-only", responder)
    assert sessions.has_active_session(owner)
    assert sessions.has_active_session(responder)


@pytest.mark.asyncio
async def test_shareable_explicit_key_selects_original_value_for_responder() -> None:
    sessions = PortableQuerySessions()
    owner = _context("owner")
    responder = _context("responder", reply_to_id="rank-menu")
    selected = AsyncMock(return_value=OutboundMessage.from_text("selected"))
    message = sessions.offer_menu(
        owner,
        PortableMenuSpec(
            choices=("rank-11", "rank-20"),
            choice_keys=("11", "20"),
            select=selected,
            prompt=OutboundMessage.from_text("rank menu"),
            shareable=True,
            claim_unknown_numeric=False,
        ),
    )
    sessions.record_delivery(
        owner, message, SendResult(delivered=True, message_id="rank-menu")
    )

    assert sessions.recognizes_shared_response("20", owner, responder)
    assert not sessions.recognizes_shared_response("2", owner, responder)
    result = await sessions.select_shared("20", owner, responder)

    assert isinstance(result, OutboundMessage)
    assert _text(result) == "selected"
    selected.assert_awaited_once_with("rank-20", responder)
    assert sessions.has_active_session(owner)
    assert not sessions.has_active_session(responder)


@pytest.mark.asyncio
async def test_shared_group_exit_does_not_close_owner_menu() -> None:
    sessions = PortableQuerySessions()
    owner = _context("owner")
    responder = _context("responder", reply_to_id="current-menu")
    sessions.offer_menu(
        owner,
        PortableMenuSpec(
            choices=("read-only",),
            select=AsyncMock(),
            prompt=OutboundMessage.from_text("menu"),
            shared_select=AsyncMock(),
            shared_choice_indexes=frozenset({1}),
            keep_open=True,
            exit_message="responder exited",
        ),
    )

    assert not sessions.recognizes_shared_response("0", owner, responder)
    result = await sessions.select_shared("0", owner, responder)
    assert result is None
    assert sessions.has_active_session(owner)
    assert not sessions.has_active_session(responder)


def test_menu_semantic_request_uses_responder_without_consuming_choice() -> None:
    sessions = PortableQuerySessions()
    owner = _context("owner")
    responder = _context("responder", reply_to_id="current-menu")
    observed: list[MessageInputContext] = []

    def semantic_request(
        value: str,
        context: MessageInputContext,
    ) -> SemanticRequest:
        observed.append(context)
        return SemanticRequest(
            ActionDefinition(value, "read only"),
            singleton_target("player", "player"),
            SemanticRequestSource.MENU,
        )

    message = sessions.offer_menu(
        owner,
        PortableMenuSpec(
            choices=("read-only", "owner-only"),
            select=AsyncMock(),
            shared_select=AsyncMock(),
            semantic_request=semantic_request,
            shared_choice_indexes=frozenset({1}),
            prompt=OutboundMessage.from_text("menu"),
        ),
    )

    sessions.record_delivery(
        owner, message, SendResult(delivered=True, message_id="current-menu")
    )
    owner_request = sessions.resolve_semantic_request("2", owner)
    shared_request = sessions.resolve_semantic_request("1", owner, responder)

    assert owner_request is not None and owner_request.action.id == "owner-only"
    assert shared_request is not None and shared_request.action.id == "read-only"
    assert sessions.resolve_semantic_request("2", owner, responder) is None
    assert observed == [owner, responder]
    assert sessions.has_active_session(owner)


@pytest.mark.asyncio
async def test_button_and_text_inputs_share_one_bound_prompt_session() -> None:
    sessions = PortableQuerySessions()
    owner = _context("member-openid")
    other_member = _context("other-openid")
    selected: list[str] = []

    async def select(value: str, _context: MessageInputContext) -> OutboundMessage:
        selected.append(value)
        return OutboundMessage.from_text(value)

    offered = sessions.offer_menu(
        owner,
        PortableMenuSpec(
            choices=("yes", "no"),
            select=select,
            prompt=OutboundMessage.from_text("choose"),
        ),
    )
    prompt = sessions.active_prompt(owner)
    assert prompt is not None
    assert offered.prompt is prompt
    action = prompt.action_data(prompt.choices[0])

    assert sessions.recognizes_response(action, owner)
    assert not sessions.recognizes_response(action, other_member)
    assert await sessions.select_action(action, other_member) is None
    result = await sessions.select(action, owner)
    assert isinstance(result, OutboundMessage)
    assert _text(result) == "yes"
    assert selected == ["yes"]
    assert await sessions.select_action(action, owner) is None
    assert await sessions.select("1", owner) is None


@pytest.mark.asyncio
async def test_selection_can_exit_and_expires_without_persistence() -> None:
    clock = _Clock()
    sessions = PortableQuerySessions(ttl_seconds=10, now=clock)

    async def search(_argument: str) -> QueryResult[str]:
        return QueryResult(choices=(QueryChoice("value", "", "selected"),))

    async def select(value: str) -> QueryResult[object]:
        return QueryResult(reply=QueryReply(text=value))

    spec = QueryOperationSpec(
        parser=lambda text: text,
        search=search,
        select=select,
        prompt_title="choose",
        not_found_message="missing",
    )
    first = _context("first")
    second = _context("second")
    await sessions.begin(first, argument="query", spec=spec)
    assert _text(await sessions.select("0", first)) == "已退出查询。"
    assert not sessions.recognizes_response("1", first)

    await sessions.begin(second, argument="query", spec=spec)
    clock.value = 10
    assert sessions.recognizes_response("1", second)
    assert _text(await sessions.select("1", second)) == (
        "查询会话已超时，请重新发送原指令。"
    )
    assert not sessions.recognizes_response("1", second)


@pytest.mark.asyncio
async def test_expired_selection_does_not_claim_an_unrelated_command() -> None:
    clock = _Clock()
    sessions = PortableQuerySessions(ttl_seconds=10, now=clock)
    context = _context("member")

    async def select(_value: str, _context: MessageInputContext) -> OutboundMessage:
        raise AssertionError

    sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=("value",),
            select=select,
            prompt=OutboundMessage.from_text("menu"),
        ),
    )
    clock.value = 10

    assert not sessions.recognizes_response("帮助", context)
    assert await sessions.select("帮助", context) is None


@pytest.mark.asyncio
async def test_query_operation_uses_service_result_contract() -> None:
    sessions = PortableQuerySessions()

    async def search(argument: str) -> QueryResult[int]:
        return QueryResult(reply=QueryReply(text=f"found:{argument}"))

    async def select(_value: int) -> QueryResult[object]:
        raise AssertionError

    operation = build_query_operation(
        sessions,
        QueryOperationSpec(
            parser=lambda text: text.removeprefix("query") or None,
            search=search,
            select=select,
            prompt_title="choose",
            not_found_message="missing",
        ),
    )

    assert _text(await operation("querytarget", _context("member"))) == "found:target"
    with pytest.raises(ValueError, match="parser rejected"):
        await operation("query", _context("member"))


@pytest.mark.asyncio
async def test_text_input_session_claims_next_response_and_supports_exit() -> None:
    sessions = PortableQuerySessions()
    context = _context("member")

    async def submit(text: str, _context: MessageInputContext) -> OutboundMessage:
        return OutboundMessage.from_text(f"value:{text}")

    sessions.offer_text_input(
        context,
        PortableTextInputSpec(
            submit=submit,
            prompt=OutboundMessage.from_text("input"),
        ),
    )
    assert sessions.recognizes_response("22:30", context)
    assert _text(await sessions.select("22:30", context)) == "value:22:30"
    assert not sessions.recognizes_response("22:30", context)

    sessions.offer_text_input(
        context,
        PortableTextInputSpec(
            submit=submit,
            prompt=OutboundMessage.from_text("input"),
        ),
    )
    assert _text(await sessions.select("0", context)) == "已退出查询。"


@pytest.mark.asyncio
async def test_deferred_menu_result_requires_explicit_caller_support() -> None:
    sessions = PortableQuerySessions()
    context = _context("member")

    async def select(_value: str, _context: MessageInputContext) -> PortableReply:
        return PortableReply(OutboundMessage.from_text("deferred"))

    sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=("value",),
            select=select,
            prompt=OutboundMessage.from_text("menu"),
        ),
    )

    with pytest.raises(PortableQuerySessionError, match="was not enabled"):
        await sessions.select("1", context)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        QueryResult[str](message="unavailable"),
        QueryResult[str](reply=QueryReply(text="result")),
        QueryResult[str](),
        QueryResult(choices=(QueryChoice("choice", "", "selected"),)),
    ],
)
async def test_query_result_replaces_text_input_instead_of_leaving_two_sessions(
    result: QueryResult[str],
) -> None:
    sessions = PortableQuerySessions()
    context = _context("owner")
    submit = AsyncMock(return_value=OutboundMessage.from_text("old input"))
    sessions.offer_text_input(
        context,
        PortableTextInputSpec(
            submit=submit,
            prompt=OutboundMessage.from_text("input"),
        ),
    )
    assert sessions.has_active_session(context)
    assert sessions.active_prompt(context) is None
    choose = AsyncMock(return_value=QueryResult(reply=QueryReply(text="selected")))
    sessions.offer(
        context,
        result,
        select=choose,
        prompt_title="choose",
        not_found_message="missing",
    )
    assert not sessions.recognizes_response("old text", context)
    assert await sessions.select("old text", context) is None
    assert sessions.has_active_session(context) == bool(result.choices)
    if result.choices:
        assert _text(await sessions.select("1", context)) == "selected"
        choose.assert_awaited_once_with("selected")
    submit.assert_not_awaited()
    assert not sessions.has_active_session(context)


@pytest.mark.asyncio
@pytest.mark.parametrize("text_input", [False, True])
async def test_all_interaction_templates_share_expiry_and_owner_isolation(
    *,
    text_input: bool,
) -> None:
    clock = _Clock()
    sessions = PortableQuerySessions(ttl_seconds=10, now=clock)
    context = _context("owner")
    callback = AsyncMock(return_value=OutboundMessage.from_text("result"))
    message = OutboundMessage.from_text("prompt")
    if text_input:
        sessions.offer_text_input(
            context,
            PortableTextInputSpec(submit=callback, prompt=message),
        )
    else:
        sessions.offer_menu(
            context,
            PortableMenuSpec(choices=("one",), select=callback, prompt=message),
        )
    assert sessions.has_active_session(context)
    assert not sessions.has_active_session(_context("stranger"))
    assert not sessions.has_active_session(_context("owner", group_id="elsewhere"))
    assert await sessions.select_action("old-button", context) is None
    assert sessions.has_active_session(context)
    clock.value = 10
    assert not sessions.has_active_session(context)
    assert await sessions.select("1", context) is None
    callback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["1", "accept", "button", "free text"])
async def test_templates_pass_current_response_context(response: str) -> None:
    sessions = PortableQuerySessions()
    owner = _context("owner")
    current = replace(
        owner,
        message=replace(owner.message, message_id="next-message", group_role="admin"),
    )
    callback = AsyncMock(return_value=OutboundMessage.from_text("result"))
    prompt = OutboundMessage.from_text("prompt")
    if response == "free text":
        sessions.offer_text_input(
            owner, PortableTextInputSpec(submit=callback, prompt=prompt)
        )
        value = response
    else:
        menu = sessions.offer_menu(
            owner,
            PortableMenuSpec(
                choices=("selected",),
                select=callback,
                prompt=prompt,
                text_inputs=(frozenset({"accept"}),),
            ),
        )
        if response == "button":
            assert menu.prompt is not None
            response = menu.prompt.action_data(menu.prompt.choices[0])
        value = "selected"
    assert await sessions.select(response, _context("stranger")) is None
    callback.assert_not_awaited()
    assert _text(await sessions.select(response, current)) == "result"
    callback.assert_awaited_once_with(value, current)
