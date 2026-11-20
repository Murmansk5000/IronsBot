# SPDX-License-Identifier: GPL-3.0-or-later
"""Serialize bounded native HTML rendering behind one application port."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from pathlib import PurePath
from time import monotonic
from traceback import extract_tb
from typing import TYPE_CHECKING

from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.render_pipeline import (
    RenderExecution,
    RenderFailureError,
    RenderRequest,
    RenderResult,
    current_render,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from typing import Any

    from ironsbot.services.seer.rendering import HtmlTemplateRenderer, TemplatePath


@dataclass(slots=True)
class RenderCoordinator:
    """Run native HTML rendering one at a time with an explicit deadline."""

    renderer: HtmlTemplateRenderer
    timeout_seconds: float
    _semaphore: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(1),
        init=False,
        repr=False,
    )

    async def execute(
        self, request: RenderRequest, prepare: Callable[[], Awaitable[bytes]]
    ) -> RenderResult:
        execution = RenderExecution()
        started = monotonic()
        outcome = "cancelled"
        token = current_render.set(execution)
        logger.info(
            "Render started: template=%s version=%s",
            request.template,
            request.data_version,
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                image = await prepare()
            _require_nonempty(image)
            if not execution.degraded:
                for write in execution.writes:
                    write()
            outcome = "degraded" if execution.degraded else "complete"
            return RenderResult(
                replace(request, cache_key=request.cache_key or execution.cache_key),
                image,
                "degraded" if execution.degraded else "complete",
            )
        except (DataUnavailableError, RenderFailureError):
            outcome = "failed"
            raise
        except Exception as error:  # noqa: BLE001 - one presentation failure boundary
            outcome = "failed"
            logger.warning(
                "Render failed: template=%s version=%s stage=%s error_type=%s",
                request.template,
                request.data_version,
                execution.stage,
                type(error).__name__,
            )
            return RenderResult(
                replace(request, cache_key=request.cache_key or execution.cache_key),
                None,
                "failed",
                execution.stage,
                type(error).__name__,
                failure_location=_error_location(error),
                elapsed_seconds=monotonic() - started,
                timeout_seconds=self.timeout_seconds,
                failure_step=str(
                    (error.__cause__ or error.__context__ or error).__dict__.get(
                        "render_step", execution.step
                    )
                ),
            )
        finally:
            current_render.reset(token)
            logger.info(
                "Render finished: template=%s stage=%s outcome=%s elapsed=%.3fs",
                request.template,
                execution.stage,
                outcome,
                monotonic() - started,
            )

    async def image(
        self, request: RenderRequest, prepare: Callable[[], Awaitable[bytes]]
    ) -> bytes:
        return (await self.execute(request, prepare)).require_image()

    async def render(
        self,
        template_path: TemplatePath,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        if current_render.get() is None:
            return await self.image(
                RenderRequest(template_name),
                lambda: self.render(
                    template_path,
                    template_name,
                    templates,
                    max_width=max_width,
                    allow_refit=allow_refit,
                ),
            )
        execution = current_render.get()
        assert execution is not None
        execution.stage = "queue"
        execution.step = "等待公共渲染队列"
        async with self._semaphore:
            execution.stage = "render"
            execution.step = "模板布局、绘制及PNG编码（底层合计）"
            return await self.renderer(
                template_path,
                template_name,
                templates,
                max_width=max_width,
                allow_refit=allow_refit,
            )


def _require_nonempty(image: bytes) -> None:
    if not image:
        msg = "renderer returned an empty image"
        raise ValueError(msg)


def _error_location(error: Exception) -> str:
    cause = error.__cause__ or error.__context__ or error
    frames = extract_tb(cause.__traceback__)
    if not frames:
        return "原始位置未提供"
    project = [
        frame
        for frame in frames
        if any(
            part in frame.filename.replace("\\", "/")
            for part in ("/ironsbot/", "/tests/")
        )
    ]
    frame = project[-1] if project else frames[-1]
    return f"{PurePath(frame.filename).name}:{frame.lineno}:{frame.name}"
