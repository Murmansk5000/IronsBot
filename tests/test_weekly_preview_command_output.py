# SPDX-License-Identifier: MIT
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import nonebot
import pytest

nonebot.init()

from ironsbot.integrations.onebot.portable_queries import (
    make_portable_operation_handler,
)
from ironsbot.services.portable_data_commands import build_portable_data_operation
from ironsbot.services.seer.data_queries import DataQueryImageReply
from tests.helpers.onebot_events import group_message_event


@pytest.mark.asyncio
async def test_weekly_preview_image_output_includes_cache_notice_and_reference() -> (
    None
):
    async def operation() -> DataQueryImageReply:
        return DataQueryImageReply(
            b"combined-image",
            "缓存时间：2026-08-10 11:00:00",
            source_url="https://github.com/example/preview-source",
        )

    references = SimpleNamespace(
        url_for=lambda _reference: "https://seerinfo.yuyuqaq.cn/preview"
    )
    matcher = SimpleNamespace(
        state={}, send=AsyncMock(return_value={"message_id": 900})
    )
    await make_portable_operation_handler(
        build_portable_data_operation(
            cast("Any", SimpleNamespace(weekly_preview=operation)),
            cast("Any", references),
        )
    )(cast("Any", matcher), {}, group_message_event("下周预告", message_id=-10))

    message = matcher.send.await_args.args[0]
    assert [part.type for part in message] == [
        "reply",
        "image",
        "text",
        "text",
    ]
    assert message.extract_plain_text() == (
        "\n缓存时间：2026-08-10 11:00:00\n相关查询：https://seerinfo.yuyuqaq.cn/preview"
    )


@pytest.mark.asyncio
async def test_weekly_preview_uses_published_source_when_reference_is_disabled() -> (
    None
):
    async def operation() -> DataQueryImageReply:
        return DataQueryImageReply(
            b"image",
            source_url="https://github.com/example/preview-source",
        )

    matcher = SimpleNamespace(
        state={}, send=AsyncMock(return_value={"message_id": 900})
    )
    await make_portable_operation_handler(
        build_portable_data_operation(
            cast("Any", SimpleNamespace(weekly_preview=operation)), None
        )
    )(cast("Any", matcher), {}, group_message_event("下周预告", message_id=-11))

    message = matcher.send.await_args.args[0]
    assert [part.type for part in message] == ["reply", "image", "text"]
    assert message.extract_plain_text() == (
        "\n相关查询：https://github.com/example/preview-source"
    )
