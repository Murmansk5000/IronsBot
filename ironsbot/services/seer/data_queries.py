# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import timedelta, timezone
from functools import partial
from typing import TYPE_CHECKING

from ironsbot.services.seer.data import load_data_generated_at
from ironsbot.services.seer.images import ImageSourceError
from ironsbot.services.seer.season_countdown import format_season_countdown
from ironsbot.services.seer.weekly_preview import load_weekly_preview_links

if TYPE_CHECKING:
    from ironsbot.config.models.seer import SeasonCountdownConfig
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource

DataQueryReply = str | bytes
CHINA_TIMEZONE = timezone(timedelta(hours=8))


class SeerDataQueryService:
    def __init__(
        self,
        data: SeerDataAccess,
        images: SeerImageSource,
        season: SeasonCountdownConfig,
    ) -> None:
        self._data = data
        self._images = images
        self._season = season

    async def weekly_preview(self) -> DataQueryReply:
        with self._data.query(load_weekly_preview_links) as links:
            image_url, _source_url = links
        try:
            return await self._images.fetch_url(image_url)
        except ImageSourceError:
            return await self._fallback_preview()

    async def data_version(self) -> str:
        with self._data.query(load_data_generated_at) as generated_at:
            if generated_at is None:
                return "❌暂无数据版本信息(这是一个bug，请反馈给开发者)"
        if (
            generated_at.tzinfo is None
            or generated_at.tzinfo.utcoffset(generated_at) is None
        ):
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        local_time = generated_at.astimezone(CHINA_TIMEZONE)
        return f"数据更新时间：{local_time:%Y-%m-%d %H:%M:%S}"

    async def season_countdown(self) -> str:
        operation = partial(format_season_countdown, config=self._season)
        with self._data.query(operation) as message:
            return message

    async def _fallback_preview(self) -> DataQueryReply:
        try:
            return await self._images.fetch("preview", "", fallback=False)
        except ImageSourceError as error:
            return f"❌获取图片失败！原因：{error}"
