# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from types import SimpleNamespace
from typing import Any, cast

import pytest

from ironsbot.integrations.onebot.message_segments import onebot_message_text
from ironsbot.services.portable_data_commands import build_portable_data_operation
from ironsbot.services.seer.data_queries import DataQueryImageReply
from tests.helpers.command_execution import operation_router
from tests.helpers.onebot_events import group_message_event
from tests.helpers.onebot_inputs import message_input_context

pytest_plugins = ("tests.test_shared_onebot_ingress",)


@pytest.mark.asyncio
async def test_weekly_preview_image_output_includes_cache_notice_and_reference(
    runtime: SimpleNamespace,
) -> None:
    async def preview() -> DataQueryImageReply:
        return DataQueryImageReply(
            b"combined-image",
            "缓存时间：2026-08-10 11:00:00",
            source_url="https://github.com/example/preview-source",
        )

    references = SimpleNamespace(
        url_for=lambda _reference: "https://seerinfo.yuyuqaq.cn/preview"
    )
    operation = build_portable_data_operation(
        cast("Any", SimpleNamespace(weekly_preview=preview)),
        cast("Any", references),
    )
    context = message_input_context(group_message_event("下周预告", message_id=-10))
    await operation_router(operation, context).ingress.handle(
        context, partial(runtime.messenger.reply_from, runtime.bot, context)
    )

    (sent,) = runtime.sends
    message = sent["message"]
    assert [part["type"] for part in message] == [
        "reply",
        "image",
        "text",
        "text",
    ]
    assert message[0] == {"type": "reply", "data": {"id": "-10"}}
    assert onebot_message_text(message) == (
        "\n缓存时间：2026-08-10 11:00:00\n相关查询：https://seerinfo.yuyuqaq.cn/preview"
    )


@pytest.mark.asyncio
async def test_weekly_preview_uses_published_source_when_reference_is_disabled(
    runtime: SimpleNamespace,
) -> None:
    async def preview() -> DataQueryImageReply:
        return DataQueryImageReply(
            b"image",
            source_url="https://github.com/example/preview-source",
        )

    operation = build_portable_data_operation(
        cast("Any", SimpleNamespace(weekly_preview=preview)), None
    )
    context = message_input_context(group_message_event("下周预告", message_id=-11))
    await operation_router(operation, context).ingress.handle(
        context, partial(runtime.messenger.reply_from, runtime.bot, context)
    )

    (sent,) = runtime.sends
    message = sent["message"]
    assert [part["type"] for part in message] == ["reply", "image", "text"]
    assert message[0] == {"type": "reply", "data": {"id": "-11"}}
    assert onebot_message_text(message) == (
        "\n相关查询：https://github.com/example/preview-source"
    )
