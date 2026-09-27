# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import TYPE_CHECKING

from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart
from ironsbot.services.messaging.image_collage import ImageCollageError
from ironsbot.services.seer.images import (
    IMAGE_UNAVAILABLE_MESSAGE,
    ImageFailureReporter,
    ImageSourceError,
)
from ironsbot.services.seer.season_countdown import (
    SeasonWindow,
    format_season_countdown,
)
from ironsbot.services.seer.weekly_preview_images import WeeklyPreviewImageError

if TYPE_CHECKING:
    from ironsbot.config.models.seer import SeasonCountdownConfig
    from ironsbot.services.messaging.image_collage import ImageCollageService
    from ironsbot.services.seer.data_query_facts import SeerDataQueryFacts
    from ironsbot.services.seer.new_content import (
        NewContentService,
        NewContentSnapshot,
    )
    from ironsbot.services.seer.weekly_preview_images import (
        WeeklyPreviewImage,
        WeeklyPreviewImageSource,
    )


@dataclass(frozen=True, slots=True)
class DataQueryImageReply:
    image: bytes
    notice: str = ""
    additional_images: tuple[bytes, ...] = ()
    source_url: str = ""

    def to_outbound(self, *, reference_url: str | None = None) -> OutboundMessage:
        parts: list[BinaryImagePart | TextPart] = [
            BinaryImagePart(image, "image/png")
            for image in dict.fromkeys((self.image, *self.additional_images))
        ]
        if self.notice:
            parts.append(TextPart(f"\n{self.notice}"))
        link = reference_url or self.source_url
        if link:
            parts.append(TextPart(f"\n相关查询：{link}"))
        return OutboundMessage(tuple(parts))


DataQueryReply = str | DataQueryImageReply
CHINA_TIMEZONE = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)


class SeerDataQueryService:
    def __init__(  # noqa: PLR0913 - query dependencies are supplied by composition
        self,
        facts: SeerDataQueryFacts,
        preview_images: WeeklyPreviewImageSource,
        season: SeasonCountdownConfig,
        new_content: NewContentService,
        image_failure_reporter: ImageFailureReporter | None = None,
        image_collage: ImageCollageService | None = None,
    ) -> None:
        self._facts = facts
        self._preview_images = preview_images
        self._season = season
        self._new_content = new_content
        self._image_failure_reporter = image_failure_reporter
        self._image_collage = image_collage

    def new_content_snapshot(self) -> NewContentSnapshot:
        return self._new_content.snapshot()

    async def weekly_preview(self) -> DataQueryReply:
        links = self._facts.weekly_preview_links()
        results = await asyncio.gather(
            *(self._preview_images.fetch(url) for url in links.image_urls),
            return_exceptions=True,
        )
        previews, failures = _partition_weekly_preview_results(results)

        for index, error in failures:
            if self._image_failure_reporter is not None:
                await self._image_failure_reporter(
                    "weekly_preview",
                    f"current_{index}",
                    ImageSourceError(str(error)),
                )
        if not previews:
            return IMAGE_UNAVAILABLE_MESSAGE

        notice = ""
        stale_previews = [preview for preview in previews if preview.stale]
        if stale_previews:
            cached_at = min(preview.cached_at for preview in stale_previews).astimezone(
                CHINA_TIMEZONE
            )
            if len(stale_previews) < len(previews):
                notice = "⚠️ 网络刷新失败，部分图片为缓存；"
            else:
                notice = "⚠️ 网络刷新失败，当前为缓存图片；"
            notice += f"缓存时间：{cached_at:%Y-%m-%d %H:%M:%S}"
        elif failures:
            notice = "⚠️ 部分预告图片获取失败，已显示可用图片。"
        images = list(dict.fromkeys(preview.data for preview in previews))
        if len(images) > 1 and self._image_collage is not None:
            try:
                images = [await self._image_collage.compose_bytes(images)]
            except ImageCollageError:
                logger.warning("weekly preview collage failed; sending original images")
        return DataQueryImageReply(
            images[0], notice, tuple(images[1:]), links.source_url
        )

    async def data_version(self) -> str:
        generated_at = self._facts.generated_at()
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
        times = self._facts.peak_season_times()
        peak = (
            None
            if times is None
            else SeasonWindow(
                name="巅峰圣战赛季",
                start_time=times.start_time,
                end_time=times.end_time,
            )
        )
        return format_season_countdown(peak, self._season)


def _partition_weekly_preview_results(
    results: list[WeeklyPreviewImage | BaseException],
) -> tuple[
    list[WeeklyPreviewImage],
    list[tuple[int, WeeklyPreviewImageError]],
]:
    previews: list[WeeklyPreviewImage] = []
    failures: list[tuple[int, WeeklyPreviewImageError]] = []
    for index, result in enumerate(results, start=1):
        if isinstance(result, WeeklyPreviewImageError):
            failures.append((index, result))
        elif isinstance(result, Exception):
            failures.append((index, WeeklyPreviewImageError.from_detail(str(result))))
        elif isinstance(result, BaseException):
            raise result
        else:
            previews.append(result)
    return previews, failures
