# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from httpx import HTTPStatusError, RequestError
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot_plugin_saa import Image, MessageFactory, MessageSegmentFactory, Text

from ironsbot.integrations.http_client import get_http_origin_client
from ironsbot.integrations.seer_data.image import PreviewImageGetter
from ironsbot.services.seer.season_countdown import format_season_countdown
from ironsbot.services.seer.weekly_preview import load_weekly_preview_links
from ironsbot.shared.messaging import finish_event_reply

from ..upstream_commands import other as upstream_other

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.matcher import Matcher

    from ..depends import SeerAPISession


async def fetch_weekly_preview_image(image_url: str) -> MessageSegmentFactory:
    try:
        response = await get_http_origin_client().get(image_url)
        response.raise_for_status()
        return Image(response.content)
    except (HTTPStatusError, RequestError):
        return await PreviewImageGetter.get("")


async def handle_preview(*, session: SeerAPISession) -> None:
    image_url, source_url = load_weekly_preview_links(session)
    msg = MessageFactory()
    msg += await fetch_weekly_preview_image(image_url)
    msg += Text(f"\n预告图来自 {source_url}")
    await msg.finish()


async def handle_data_version(
    *,
    matcher: Matcher,
    session: SeerAPISession,
) -> None:
    await upstream_other.handle_data_version(
        matcher=matcher,
        session=session,
    )


async def handle_season_countdown(
    *,
    matcher: Matcher,
    event: Event,
    session: SeerAPISession,
) -> None:
    message = format_season_countdown(session)
    if isinstance(event, MessageEvent):
        await finish_event_reply(matcher, event, message)
    await matcher.finish(message)
