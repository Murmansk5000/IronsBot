# SPDX-License-Identifier: MIT
from __future__ import annotations

from types import SimpleNamespace
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
from ironsbot.services.portable_seer_commands import (
    build_portable_data_query_operation,
)
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.data_queries import DataQueryImageReply
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

if TYPE_CHECKING:
    from ironsbot.services.seer.data_queries import SeerDataQueryService
    from ironsbot.services.seer.external_references import SeerInfoReferences


def _context(text: str) -> MessageInputContext:
    actor = ActorRef(Platform.ONEBOT, "1")
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.ONEBOT,
            actor=actor,
            conversation=ConversationRef(Platform.ONEBOT, "private", actor.id),
            message_id="message-1",
            text=text,
        ),
        mentions_bot=False,
    )


@pytest.mark.asyncio
async def test_weekly_preview_output_includes_notice_and_reference() -> None:
    async def weekly_preview() -> DataQueryImageReply:
        return DataQueryImageReply(b"image", "缓存时间：2026-08-10 11:00:00")

    references = SimpleNamespace(
        url_for=lambda _reference: "https://seerinfo.yuyuqaq.cn/preview"
    )
    service = SimpleNamespace(weekly_preview=weekly_preview)
    operation = build_portable_data_query_operation(
        cast("SeerDataQueryService", service),
        cast("SeerInfoReferences", references),
    )

    message = cast(
        "OutboundMessage",
        await operation("下周预告", _context("下周预告")),
    )

    assert message.parts == (
        BinaryImagePart(b"image", "image/png"),
        TextPart("\n缓存时间：2026-08-10 11:00:00"),
        TextPart("\n相关查询：https://seerinfo.yuyuqaq.cn/preview"),
    )


@pytest.mark.asyncio
async def test_data_query_maps_unavailable_database_to_a_reply() -> None:
    async def data_version() -> str:
        raise DataUnavailableError

    service = SimpleNamespace(data_version=data_version)
    operation = build_portable_data_query_operation(
        cast("SeerDataQueryService", service),
        None,
    )

    message = cast(
        "OutboundMessage",
        await operation("数据版本", _context("数据版本")),
    )

    assert message.parts == (TextPart(DATABASE_UNAVAILABLE_MESSAGE),)
