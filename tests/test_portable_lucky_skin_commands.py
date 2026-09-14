from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.portable_lucky_skin_commands import (
    build_portable_lucky_skin_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.lucky_skin_window import (
    LuckySkinWatchItem,
    LuckySkinWindowOffer,
    LuckySkinWindowResult,
)
from ironsbot.services.seer.pet_query import PetImageSelection
from ironsbot.services.seer.query_result import QueryChoice, QueryReply, QueryResult

if TYPE_CHECKING:
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService
    from ironsbot.services.seer.pet_query import PetQueryService


@dataclass
class _FakeLuckySkinWindow:
    cached: bool = False

    def __post_init__(self) -> None:
        self.events: list[str] = []
        self.result = LuckySkinWindowResult(
            "2026-09-14",
            712345678,
            (
                LuckySkinWindowOffer(101, 1400101, "皮肤甲", watched=False),
                LuckySkinWindowOffer(102, 1400102, "皮肤乙", watched=False),
            ),
            self.cached,
        )

    def cached_for_actor(self, actor: ActorRef) -> LuckySkinWindowResult | None:
        self.events.append(f"cache:{actor.id}")
        return self.result if self.cached else None

    async def check_for_actor(self, actor: ActorRef) -> LuckySkinWindowResult:
        self.events.append(f"check:{actor.id}")
        return self.result

    async def result_message(
        self,
        result: LuckySkinWindowResult,
        *,
        actor: ActorRef,
    ) -> OutboundMessage:
        self.events.append(f"render:{actor.id}:{result.day}")
        return OutboundMessage.from_text("window result")

    @staticmethod
    def detail_choices(
        result: LuckySkinWindowResult,
    ) -> tuple[QueryChoice[PetImageSelection], ...]:
        return tuple(
            QueryChoice(
                offer.name,
                str(offer.skin_id),
                PetImageSelection(
                    offer.resource_id,
                    offer.name,
                    skin_id=offer.skin_id,
                ),
            )
            for offer in result.offers
        )

    def watch_list_message(self, actor: ActorRef) -> str:
        return f"watch list:{actor.id}"

    def resolve_watch_candidates(
        self,
        actor: ActorRef,
        argument: str,
    ) -> tuple[LuckySkinWatchItem, ...]:
        self.events.append(f"resolve:{actor.id}:{argument}")
        first = LuckySkinWatchItem(101, 1400101, "皮肤甲")
        if argument == "many":
            return (first, LuckySkinWatchItem(102, 1400102, "皮肤乙"))
        return (first,) if argument == "101" else ()

    def watch_change_message(
        self,
        actor: ActorRef,
        item: LuckySkinWatchItem,
        *,
        watched: bool,
    ) -> str:
        action = "add" if watched else "remove"
        return f"{action}:{actor.id}:{item.skin_id}"

    def watch_clear_message(self, actor: ActorRef) -> str:
        return f"clear:{actor.id}"

    def watch_reset_message(self, actor: ActorRef) -> str:
        return f"reset:{actor.id}"


class _FakePet:
    async def select_image(
        self,
        selection: PetImageSelection,
    ) -> QueryResult[object]:
        return QueryResult(reply=QueryReply(text=f"skin:{selection.skin_id}"))


class _UnavailablePet:
    async def select_image(
        self,
        _selection: PetImageSelection,
    ) -> QueryResult[object]:
        raise DataUnavailableError


def _context(text: str = "") -> MessageInputContext:
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "user-openid",
        account_id="app-id",
    )
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=actor,
            conversation=ConversationRef(
                Platform.QQ_OFFICIAL,
                "private",
                actor.id,
                account_id=actor.account_id,
            ),
            message_id="message-id",
            text=text,
        ),
        mentions_bot=False,
    )


def _text(message: OutboundMessage) -> str:
    part = message.parts[0]
    assert isinstance(part, TextPart)
    return part.text


def _operations(
    service: _FakeLuckySkinWindow,
    sessions: PortableQuerySessions,
    pet: object | None = None,
):
    return build_portable_lucky_skin_operations(
        cast("LuckySkinWindowService", service),
        cast("PetQueryService", pet or _FakePet()),
        sessions,
    )


@pytest.mark.asyncio
async def test_portable_lucky_window_uses_confirmation_delivery_gate() -> None:
    service = _FakeLuckySkinWindow()
    sessions = PortableQuerySessions()
    context = _context("橱窗")
    query = _operations(service, sessions)["seer.lucky_skin_window.query"]

    confirmation = await query("橱窗", context)

    assert isinstance(confirmation, OutboundMessage)
    assert "是否继续" in _text(confirmation)
    assert not sessions.recognizes_response("普通聊天", context)
    assert sessions.recognizes_response("是", context)
    selected = await sessions.select("是", context, allow_deferred=True)
    assert isinstance(selected, PortableReply)
    assert "正在查询" in _text(selected.message)
    assert service.events == ["cache:user-openid"]

    await selected.commit_delivery()
    assert selected.follow_up is not None
    final = await selected.follow_up()

    assert isinstance(final, OutboundMessage)
    assert _text(final) == "window result"
    assert service.events[-2:] == [
        "check:user-openid",
        "render:user-openid:2026-09-14",
    ]


@pytest.mark.asyncio
async def test_portable_lucky_window_cached_result_opens_detail_menu() -> None:
    service = _FakeLuckySkinWindow(cached=True)
    sessions = PortableQuerySessions()
    context = _context("橱窗")
    query = _operations(service, sessions)["seer.lucky_skin_window.query"]

    result = await query("橱窗", context)
    selected = await sessions.select("1", context)

    assert isinstance(result, OutboundMessage)
    assert _text(result) == "window result"
    assert isinstance(selected, OutboundMessage)
    assert _text(selected) == "skin:101"


@pytest.mark.asyncio
async def test_lucky_window_detail_reports_unavailable_database() -> None:
    service = _FakeLuckySkinWindow(cached=True)
    sessions = PortableQuerySessions()
    context = _context("橱窗")
    query = _operations(service, sessions, _UnavailablePet())[
        "seer.lucky_skin_window.query"
    ]

    await query("橱窗", context)
    selected = await sessions.select("1", context)

    assert isinstance(selected, OutboundMessage)
    assert _text(selected) == DATABASE_UNAVAILABLE_MESSAGE


@pytest.mark.asyncio
async def test_portable_lucky_watch_commands_share_service_and_menu() -> None:
    service = _FakeLuckySkinWindow()
    sessions = PortableQuerySessions()
    context = _context()
    operations = _operations(service, sessions)

    assert set(operations) == {
        "seer.lucky_skin_window.query",
        "seer.lucky_skin_window.watch.list",
        "seer.lucky_skin_window.watch.add",
        "seer.lucky_skin_window.watch.remove",
        "seer.lucky_skin_window.watch.clear",
        "seer.lucky_skin_window.watch.reset",
    }

    watch_list = await operations["seer.lucky_skin_window.watch.list"](
        "关注橱窗",
        context,
    )
    added = await operations["seer.lucky_skin_window.watch.add"](
        "关注橱窗101",
        context,
    )
    menu = await operations["seer.lucky_skin_window.watch.remove"](
        "退订橱窗many",
        context,
    )
    removed = await sessions.select("2", context)
    cleared = await operations["seer.lucky_skin_window.watch.clear"](
        "清空关注橱窗",
        context,
    )
    reset = await operations["seer.lucky_skin_window.watch.reset"](
        "重置关注橱窗",
        context,
    )

    assert _text(cast("OutboundMessage", watch_list)) == "watch list:user-openid"
    assert _text(cast("OutboundMessage", added)) == "add:user-openid:101"
    assert "皮肤甲" in _text(cast("OutboundMessage", menu))
    assert isinstance(removed, OutboundMessage)
    assert _text(removed) == "remove:user-openid:102"
    assert _text(cast("OutboundMessage", cleared)) == "clear:user-openid"
    assert _text(cast("OutboundMessage", reset)) == "reset:user-openid"
