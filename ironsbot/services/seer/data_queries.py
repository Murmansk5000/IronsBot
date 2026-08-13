# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone
from functools import partial
from typing import TYPE_CHECKING

from ironsbot.services.seer.data import load_data_generated_at
from ironsbot.services.seer.season_countdown import format_season_countdown
from ironsbot.services.seer.weekly_preview import load_weekly_preview_links
from ironsbot.services.seer.weekly_preview_images import WeeklyPreviewImageError

if TYPE_CHECKING:
    from ironsbot.config.models.seer import SeasonCountdownConfig
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.new_content import (
        NewContentService,
        NewContentSnapshot,
    )
    from ironsbot.services.seer.weekly_preview_images import WeeklyPreviewImageSource


@dataclass(frozen=True, slots=True)
class DataQueryImageReply:
    image: bytes
    notice: str = ""


DataQueryReply = str | bytes | DataQueryImageReply
CHINA_TIMEZONE = timezone(timedelta(hours=8))


class SeerDataQueryService:
    def __init__(
        self,
        data: SeerDataAccess,
        preview_images: WeeklyPreviewImageSource,
        season: SeasonCountdownConfig,
        new_content: NewContentService,
    ) -> None:
        self._data = data
        self._preview_images = preview_images
        self._season = season
        self._new_content = new_content

    def new_content_snapshot(self) -> NewContentSnapshot:
        return self._new_content.snapshot()

    async def weekly_preview(self) -> DataQueryReply:
        with self._data.query(load_weekly_preview_links) as links:
            image_url, _source_url = links
        try:
            preview = await self._preview_images.fetch(image_url)
        except WeeklyPreviewImageError as error:
            return f"❌获取图片失败！原因：{error}"
        notice = ""
        if preview.stale:
            cached_at = preview.cached_at.astimezone(CHINA_TIMEZONE)
            notice = (
                "⚠️ 网络刷新失败，当前为缓存图片；"
                f"缓存时间：{cached_at:%Y-%m-%d %H:%M:%S}"
            )
        return DataQueryImageReply(preview.data, notice)

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
