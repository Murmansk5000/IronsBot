# SPDX-License-Identifier: MIT
"""Revision-only presentation through the existing public render coordinator."""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart
from ironsbot.core.tasks import run_owned_blocking
from ironsbot.core.time import TZ_CN
from ironsbot.services.messaging.image_collage import ImageCollageError
from ironsbot.services.seer.render_pipeline import RenderRequest

from .edit_diff import media_changes, text_changes
from .parser import dynamic_content, dynamic_image_urls
from .revisions import delivery_key, media_identity, revision_meta

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.services.messaging.image_collage import ImageCollageService
    from ironsbot.services.seer.render_coordinator import RenderCoordinator

    from .delivery_ledger import DynamicDeliveryLedger
    from .edit_diff import ImageComparison

_LOGGER = logging.getLogger(__name__)
_TEMPLATES = Path(__file__).parent / "templates"
FALLBACK_SIDE_CHARS = 700
FALLBACK_MAX_CHARS = 1700


def edit_notice(item: dict[str, Any], pub_ts: int, name: str | None) -> OutboundMessage:
    meta = revision_meta(item)
    published = datetime.fromtimestamp(pub_ts, TZ_CN).strftime("%Y-%m-%d %H:%M:%S")
    observed = datetime.fromtimestamp(meta["observed_at"], TZ_CN).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    return OutboundMessage.from_text(
        f"【{name or 'B站'}动态已修改】\n原发布时间：{published}\n"
        f"发现修改时间：{observed}（北京时间，非官方编辑时间）\n"
        f"https://t.bilibili.com/{item['id_str']}"
    )


def _data_url(content: bytes | None) -> str:
    return (
        "data:image/png;base64," + base64.b64encode(content).decode() if content else ""
    )


@dataclass(frozen=True, slots=True)
class BiliEditRenderer:
    coordinator: RenderCoordinator
    ledger: DynamicDeliveryLedger
    collage: ImageCollageService
    compare: Callable[[bytes | None, bytes | None], ImageComparison]
    spawn: TaskSpawner

    async def _render(
        self, key: str, title: str, fallback: str, **values: Any
    ) -> OutboundMessage:
        if len(fallback) > FALLBACK_MAX_CHARS:
            fallback = fallback[:FALLBACK_MAX_CHARS] + "\n对照较长，以上为节选。"
        result = await self.coordinator.execute(
            RenderRequest("bilibili_edit_v1", fallback, "edit-v1", key),
            lambda: self.coordinator.render(
                _TEMPLATES,
                "edit.html.j2",
                {"title": title, "fragments": (), "rows": (), **values},
                max_width=1200,
                allow_refit=False,
            ),
        )
        return (
            OutboundMessage((BinaryImagePart(result.image, "image/png", "edit.png"),))
            if result.image
            else OutboundMessage.from_text(
                result.fallback_text, request_succeeded=False
            )
        )

    async def text(self, item: dict[str, Any]) -> OutboundMessage | None:
        meta = revision_meta(item)
        if not meta.get("text_changed"):
            return None
        before, after = dynamic_content(meta["before"]), dynamic_content(item)
        fallback = (
            f"修改前：\n{before[:FALLBACK_SIDE_CHARS]}\n"
            f"修改后：\n{after[:FALLBACK_SIDE_CHARS]}"
        )
        if max(len(before), len(after)) > FALLBACK_SIDE_CHARS:
            fallback += "\n文字对照较长，仅展示节选；完整新版请查看动态链接。"
        return await self._render(
            delivery_key(item) + ":text",
            "动态正文修改对照",
            fallback,
            fragments=text_changes(before, after),
        )

    async def _asset(
        self, item: dict[str, Any], url: str, *, before: bool
    ) -> bytes | None:
        key = delivery_key(item)
        source = hashlib.sha256(media_identity(url).encode()).hexdigest()
        try:
            try:
                content = self.ledger.load_media_source(key, source)
            except (OSError, ValueError):
                content = None
            if content is not None:
                return content
            if before:
                content = self._previous_asset(item, url)
                if content is not None:
                    self.ledger.save_media_source(key, source, content)
                    return content
            parsed = urlsplit(url)
            if parsed.scheme == "http" and (parsed.hostname or "").endswith(
                ".hdslb.com"
            ):
                url = urlunsplit(
                    ("https", parsed.netloc, parsed.path, parsed.query, "")
                )
            content = await self.collage.fetch_image(url, self.collage.max_source_bytes)
            if not content or len(content) > self.collage.max_source_bytes:
                return None
            inspect = self.collage.inspect_animation
            if inspect is not None:
                await run_owned_blocking(
                    lambda: inspect(content),
                    spawn=self.spawn,
                    name="bilibili.edit.inspect",
                )
            self.ledger.save_media_source(key, source, content)
        except (
            OSError,
            ValueError,
            ConnectionError,
            TimeoutError,
            ImageCollageError,
        ) as error:
            _LOGGER.warning(
                "Bilibili edit asset unavailable: key=%s side=%s error=%s",
                key,
                "before" if before else "after",
                type(error).__name__,
            )
            return None
        else:
            return content

    def _previous_asset(self, item: dict[str, Any], url: str) -> bytes | None:
        previous = revision_meta(item)["previous_key"]
        for identity in (url, media_identity(url)):
            try:
                content = self.ledger.load_media_source(
                    previous, hashlib.sha256(identity.encode()).hexdigest()
                )
            except (OSError, ValueError):
                content = None
            if content is not None:
                return content
        # A single-image frozen message is a valid source only if its original
        # media identity matches; an already-combined collage is not an original.
        try:
            entry = self.ledger.queue_entry(previous)
        except ValueError:
            return None
        urls = dynamic_image_urls(entry.get("item", {}))
        if len(urls) == 1 and media_identity(urls[0]) == media_identity(url):
            try:
                found, message = self.ledger.load_media(previous)
            except (OSError, ValueError):
                return None
            if found and message and len(message.parts) == 1:
                part = message.parts[0]
                if isinstance(part, BinaryImagePart):
                    return part.content
        return None

    async def media(self, item: dict[str, Any]) -> OutboundMessage | None:
        try:
            return await self._media(item)
        except Exception as error:  # noqa: BLE001 - truthful comparison fallback
            _LOGGER.warning(
                "Bilibili edit comparison unavailable: %s", type(error).__name__
            )
            return OutboundMessage.from_text(
                "图片已修改，对照准备失败，暂无法可靠比较；请查看动态。\n"
                f"https://t.bilibili.com/{item['id_str']}",
                request_succeeded=False,
            )

    async def _media(self, item: dict[str, Any]) -> OutboundMessage | None:
        meta = revision_meta(item)
        if not meta.get("images_changed"):
            return None
        before, after = dynamic_image_urls(meta["before"]), dynamic_image_urls(item)
        rows, descriptions = [], []
        for change in media_changes(before, after):
            old = (
                await self._asset(item, before[change.before_index], before=True)
                if change.before_index is not None
                else None
            )
            new = (
                await self._asset(item, after[change.after_index], before=False)
                if change.after_index is not None
                else None
            )
            comparison = await run_owned_blocking(
                lambda old=old, new=new: self.compare(old, new),
                spawn=self.spawn,
                name="bilibili.edit.compare",
            )
            if comparison.identical and not change.moved:
                continue
            panels = comparison.panels or ((old, new),)
            note = (
                "仅调整顺序，图片像素未变。"
                if change.moved and comparison.identical
                else comparison.note
            )
            descriptions.append(change.label + "；" + note)
            for left, right in panels:
                rows.append(
                    {
                        "label": change.label,
                        "note": note,
                        "before": _data_url(left),
                        "after": _data_url(right),
                        "before_missing": "新增图片，无旧图"
                        if change.before_index is None
                        else "旧图不可用，无法对比",
                        "after_missing": "图片已删除"
                        if change.after_index is None
                        else "新图暂不可用，无法展示",
                    }
                )
        if not rows:
            return None
        fallback = (
            "\n".join(descriptions) + f"\nhttps://t.bilibili.com/{item['id_str']}"
        )
        parts = []
        for index, row in enumerate(rows):
            message = await self._render(
                f"{delivery_key(item)}:image:{index}",
                "动态图片修改对照",
                fallback,
                rows=[row],
            )
            if any(isinstance(part, TextPart) for part in message.parts):
                return message
            parts.extend(message.parts)
        return OutboundMessage(tuple(parts))
