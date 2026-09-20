from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.portable_pet_config_commands import (
    build_portable_pet_config_operation,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.query_result import QueryChoice, QueryReply, QueryResult

if TYPE_CHECKING:
    from ironsbot.services.pet_config import PetConfigQueryService


class _PetConfig:
    async def search(self, argument: str) -> QueryResult[int]:
        if argument == "雷":
            return QueryResult(
                choices=(
                    QueryChoice("雷伊", "70", 70),
                    QueryChoice("雷锘", "71", 71),
                )
            )
        if argument == "雷伊":
            return QueryResult(reply=QueryReply(image=b"pet-config"))
        return QueryResult()

    async def select(self, pet_id: int) -> QueryResult[object]:
        return QueryResult(
            reply=QueryReply(
                leading_text=f"精灵 {pet_id}\n",
                image=f"image-{pet_id}".encode(),
            )
        )


def _context(text: str) -> MessageInputContext:
    actor = ActorRef(Platform.QQ_OFFICIAL, "user", account_id="bot")
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=actor,
            conversation=ConversationRef(
                Platform.QQ_OFFICIAL,
                "private",
                actor.id,
                account_id="bot",
            ),
            message_id=f"message-{text}",
            text=text,
        ),
        mentions_bot=False,
    )


def _operation(sessions: PortableQuerySessions):
    return build_portable_pet_config_operation(
        cast("PetConfigQueryService", _PetConfig()),
        sessions,
        image_command_texts=frozenset({"配置"}),
    )


@pytest.mark.asyncio
async def test_portable_pet_config_returns_binary_image() -> None:
    result = await _operation(PortableQuerySessions())("雷伊配置", _context("雷伊配置"))

    assert isinstance(result, OutboundMessage)
    assert result.parts == (BinaryImagePart(b"pet-config", "image/png"),)


@pytest.mark.asyncio
async def test_portable_pet_config_reuses_numeric_selection_session() -> None:
    sessions = PortableQuerySessions()
    context = _context("雷配置")

    prompt = await _operation(sessions)("雷配置", context)
    selected = await sessions.select("2", context)

    assert isinstance(prompt, OutboundMessage)
    assert isinstance(prompt.parts[0], TextPart)
    assert "1. 雷伊（70）" in prompt.parts[0].text
    assert selected is not None
    assert selected.parts == (
        TextPart("精灵 71\n"),
        BinaryImagePart(b"image-71", "image/png"),
    )


@pytest.mark.asyncio
async def test_portable_pet_config_does_not_claim_reserved_image_command() -> None:
    operation = _operation(PortableQuerySessions())

    with pytest.raises(ValueError, match="parser rejected"):
        await operation("配置", _context("配置"))
