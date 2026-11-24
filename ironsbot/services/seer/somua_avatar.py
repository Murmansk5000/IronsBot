# SPDX-License-Identifier: GPL-3.0-or-later
"""Attach optional images without changing Somua observations or query work."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING

from ironsbot.extensions.somua_avatar import (
    SomuaAvatarParts,
    SomuaAvatarRequest,
    SomuaAvatarUnavailable,
)
from ironsbot.services.seer.render_pipeline import (
    RenderRequest,
    current_render,
    mark_render_degraded,
    mark_render_step,
    publish_render_cache,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.extensions.somua_avatar import SomuaAvatarProvider
    from ironsbot.services.seer.query_result import QueryReply
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.render_coordinator import RenderCoordinator
    from ironsbot.services.seer.render_pipeline import RenderResult
    from ironsbot.services.seer.somua_models import SomuaParts

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SomuaAvatarImages:
    coordinator: RenderCoordinator
    cache: RenderCache
    provider: SomuaAvatarProvider | None = None
    report_failure: Callable[[RenderResult], Awaitable[None]] | None = None

    def register_provider(self, provider: SomuaAvatarProvider) -> None:
        if self.provider is not None:
            message = "Somua avatar provider is already registered"
            raise ValueError(message)
        self.provider = provider

    async def attach(self, parts: SomuaParts, reply: QueryReply) -> QueryReply:
        provider = self.provider
        if provider is None:
            return reply
        request = SomuaAvatarRequest(SomuaAvatarParts(**asdict(parts)))
        notice = ""

        async def prepare() -> bytes:
            nonlocal notice
            mark_render_step("准备苏摩资源版本")
            async with provider.prepare(request) as session:
                if not session.resource_version or not session.renderer_fingerprint:
                    message = "Somua avatar provider omitted its version"
                    raise ValueError(message)
                notice = session.notice
                if session.degraded:
                    mark_render_degraded()
                key = hashlib.sha256(
                    json.dumps(
                        [
                            "somua-avatar-v1",
                            asdict(request),
                            session.resource_version,
                            session.renderer_fingerprint,
                        ],
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                execution = current_render.get()
                assert execution is not None
                execution.cache_key = key
                entry = self.cache.entry("somua_avatar", key)
                image = entry.get()
                if image is None:
                    image = await self.coordinator.render_backend(
                        session.render, step="苏摩骨骼绘制及PNG编码"
                    )
                    publish_render_cache(lambda data=image: entry.put(data))
                return image

        result = await self.coordinator.execute(
            RenderRequest("somua_avatar", fallback_text=reply.text), prepare
        )
        if result.image is None:
            if (
                self.report_failure is not None
                and result.exception_type != SomuaAvatarUnavailable.__name__
            ):
                try:
                    await self.report_failure(result)
                except Exception as error:  # noqa: BLE001 - notice is not the reply
                    logger.warning(
                        "Somua render failure notice failed: error_type=%s",
                        type(error).__name__,
                    )
            return replace(
                reply,
                image_error="苏摩图片暂不可用，已保留文字详情。",
                complete=False,
            )
        text = f"{reply.text}\n{notice}" if notice else reply.text
        return replace(
            reply,
            image=result.image,
            text=text,
            complete=reply.complete and result.status == "complete",
        )
