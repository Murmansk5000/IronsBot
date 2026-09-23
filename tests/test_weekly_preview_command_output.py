# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from contextlib import suppress
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import nonebot
from nonebot.exception import FinishedException

nonebot.init()

from ironsbot.plugins.onebot.seer.query.commands import data_queries
from ironsbot.services.seer.data_queries import DataQueryImageReply
from ironsbot.services.seer.external_references import SeerInfoReference
from tests.helpers.onebot_events import group_message_event


def test_weekly_preview_image_output_includes_cache_notice_and_reference() -> None:
    async def operation() -> DataQueryImageReply:
        return DataQueryImageReply(b"image", "缓存时间：2026-08-10 11:00:00")

    references = SimpleNamespace(
        url_for=lambda _reference: "https://seerinfo.yuyuqaq.cn/preview"
    )
    matcher = SimpleNamespace(state={}, finish=AsyncMock(side_effect=FinishedException))
    with suppress(FinishedException):
        asyncio.run(
            data_queries._finish_query(
                operation,
                matcher=cast("Any", matcher),
                event=group_message_event(message_id=-10),
                references=cast("Any", references),
                reference=SeerInfoReference.WEEKLY_PREVIEW,
            )
        )

    message = matcher.finish.await_args.args[0]
    assert [part.type for part in message] == ["reply", "image", "text", "text"]
    assert message.extract_plain_text() == (
        "\n缓存时间：2026-08-10 11:00:00\n相关查询：https://seerinfo.yuyuqaq.cn/preview"
    )
