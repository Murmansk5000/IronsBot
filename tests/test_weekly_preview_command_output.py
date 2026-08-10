# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from contextlib import suppress
from types import SimpleNamespace
from typing import Any, cast

import nonebot
from nonebot.exception import FinishedException
from typing_extensions import Self

nonebot.init()

from ironsbot.plugins.seer.query.commands import data_queries
from ironsbot.services.seer.data_queries import DataQueryImageReply
from ironsbot.services.seer.external_references import SeerInfoReference


class _MessageFactory:
    latest: _MessageFactory | None = None

    def __init__(self, content: object) -> None:
        self.parts = [content]
        type(self).latest = self

    def __iadd__(self, content: object) -> Self:
        self.parts.append(content)
        return self

    async def finish(self) -> None:
        raise FinishedException


def test_weekly_preview_image_output_includes_cache_notice_and_reference(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(data_queries, "MessageFactory", _MessageFactory)

    async def operation() -> DataQueryImageReply:
        return DataQueryImageReply(b"image", "缓存时间：2026-08-10 11:00:00")

    references = SimpleNamespace(
        url_for=lambda _reference: "https://seerinfo.yuyuqaq.cn/preview"
    )
    with suppress(FinishedException):
        asyncio.run(
            data_queries._finish_query(
                operation,
                matcher=cast("Any", object()),
                references=cast("Any", references),
                reference=SeerInfoReference.WEEKLY_PREVIEW,
            )
        )

    message = _MessageFactory.latest
    assert message is not None
    assert message.parts[1:] == [
        "\n缓存时间：2026-08-10 11:00:00",
        "\n相关查询：https://seerinfo.yuyuqaq.cn/preview",
    ]
