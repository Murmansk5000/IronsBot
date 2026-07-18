# SPDX-License-Identifier: GPL-3.0-or-later
# NoneBot inspects handler annotations at runtime.
# ruff: noqa: TC001, TC002
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone

from httpx import HTTPStatusError, RequestError
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot_plugin_saa import Image, MessageFactory, MessageSegmentFactory
from seerapi_models import ApiMetadataORM
from sqlmodel import select

from ironsbot.config.models.seer import SeasonCountdownConfig
from ironsbot.integrations.http_client import get_http_origin_client
from ironsbot.integrations.seer_data.image import PreviewImageGetter
from ironsbot.services.seer.season_countdown import format_season_countdown
from ironsbot.services.seer.weekly_preview import load_weekly_preview_links

from ..depends import SeerAPISession
from .query_replies import finish_query_reply


async def fetch_weekly_preview_image(image_url: str) -> MessageSegmentFactory:
    try:
        response = await get_http_origin_client().get(image_url)
        response.raise_for_status()
        return Image(response.content)
    except (HTTPStatusError, RequestError):
        return await PreviewImageGetter.get("")


async def handle_preview(*, session: SeerAPISession) -> None:
    image_url, _source_url = load_weekly_preview_links(session)
    msg = MessageFactory()
    msg += await fetch_weekly_preview_image(image_url)
    await msg.finish()


async def handle_data_version(
    *,
    matcher: Matcher,
    session: SeerAPISession,
) -> None:
    metadata = session.exec(select(ApiMetadataORM)).first()
    if metadata is None:
        await matcher.finish("❌暂无数据版本信息(这是一个bug，请反馈给开发者)")

    generated_at = metadata.generate_time
    if (
        generated_at.tzinfo is None
        or generated_at.tzinfo.utcoffset(generated_at) is None
    ):
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    local_time = generated_at.astimezone(timezone(timedelta(hours=8)))
    await matcher.finish(f"数据更新时间：{local_time:%Y-%m-%d %H:%M:%S}")


@dataclass(frozen=True, slots=True)
class SeasonCountdownHandler:
    config: SeasonCountdownConfig

    async def handle(
        self,
        *,
        matcher: Matcher,
        event: Event,
        session: SeerAPISession,
    ) -> None:
        await finish_query_reply(
            matcher,
            event,
            format_season_countdown(session, self.config),
        )
