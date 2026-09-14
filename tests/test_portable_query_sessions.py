from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessionError,
    PortableQuerySessions,
    PortableTextInputSpec,
    QueryOperationSpec,
    build_query_operation,
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


@dataclass(slots=True)
class _Clock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value


def _context(
    actor_id: str,
    *,
    group_id: str = "group-a",
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
        ),
        mentions_bot=True,
    )


def _text(message: OutboundMessage | None) -> str:
    assert message is not None
    part = message.parts[0]
    assert isinstance(part, TextPart)
    return part.text


@pytest.mark.asyncio
async def test_selection_is_scoped_by_opaque_actor_and_conversation() -> None:
    sessions = PortableQuerySessions()

    async def search(_argument: str) -> QueryResult[int]:
        return QueryResult(
            choices=(
                QueryChoice("first", "101", 101),
                QueryChoice("second", "202", 202),
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

    assert "1. first" in _text(result)
    assert "202" in _text(result)
    assert sessions.recognizes_response("2", owner)
    assert not sessions.recognizes_response("2", other_member)
    assert not sessions.recognizes_response("2", other_group)
    assert "序号无效" in _text(await sessions.select("9", owner))
    assert sessions.recognizes_response("2", owner)
    assert _text(await sessions.select("2", owner)) == "selected:202"
    assert not sessions.recognizes_response("2", owner)


@pytest.mark.asyncio
async def test_button_and_text_inputs_share_one_bound_prompt_session() -> None:
    sessions = PortableQuerySessions()
    owner = _context("member-openid")
    other_member = _context("other-openid")
    selected: list[str] = []

    async def select(value: str) -> OutboundMessage:
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
    assert not sessions.recognizes_response("1", second)
    assert await sessions.select("1", second) is None


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

    async def submit(text: str) -> OutboundMessage:
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

    async def select(_value: str) -> PortableReply:
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
