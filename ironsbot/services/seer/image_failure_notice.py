# SPDX-License-Identifier: MIT
"""Route Seer image source failures to restricted operational notices."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.outbound import ExecutionIdentity
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.seer.images import ImageFailureReporter, ImageSourceError

logger = logging.getLogger(__name__)
_MAX_ERROR_LENGTH = 800


def _safe_error_text(error: ImageSourceError) -> str:
    def public_url(match: re.Match[str]) -> str:
        try:
            parts = urlsplit(match.group())
            return urlunsplit(
                (parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", "")
            )
        except ValueError:
            return "<redacted-url>"

    return re.sub(r"https?://[^\s)]+", public_url, str(error))[:_MAX_ERROR_LENGTH]


@runtime_checkable
class BatchImageFailureReporter(Protocol):
    async def report_batch(
        self,
        failures: tuple[tuple[str, str, ImageSourceError], ...],
        identity: ExecutionIdentity | None = None,
        *,
        degraded: bool = False,
    ) -> None: ...


async def report_render_asset_failures(
    reporter: ImageFailureReporter,
    failures: tuple[tuple[str, str, ImageSourceError], ...],
    identity: ExecutionIdentity | None,
) -> None:
    if not failures:
        return
    try:
        if isinstance(reporter, BatchImageFailureReporter):
            await reporter.report_batch(failures, identity=identity, degraded=True)
        else:
            await reporter(*failures[0])
    except Exception:
        logger.exception("asset failure notice failed; continuing partial render")


@dataclass(frozen=True, slots=True)
class AdminImageFailureReporter:
    admin_notices: AdminNoticeService
    identity_resolver: (
        Callable[[ExecutionIdentity], Awaitable[ExecutionIdentity]] | None
    ) = None

    async def __call__(
        self,
        kind: str,
        key: str,
        error: ImageSourceError,
    ) -> None:
        await self.report_batch(((kind, key, error),))

    async def report_batch(
        self,
        failures: tuple[tuple[str, str, ImageSourceError], ...],
        identity: ExecutionIdentity | None = None,
        *,
        degraded: bool = False,
    ) -> None:
        if not failures:
            return
        if identity is not None and self.identity_resolver is not None:
            try:
                identity = await self.identity_resolver(identity)
            except Exception:
                logger.exception("failed to resolve executing bot display name")
        lines = [
            f"素材类型：{kind}\n资源标识：{key}\n"
            f"异常：{type(error).__name__}: {_safe_error_text(error)}"
            for kind, key, error in failures
        ]
        outcome = (
            "\n处理结果：失败素材已替换为占位图，资料图继续生成；本次结果不写入缓存。"
            if degraded
            else ""
        )
        try:
            await self.admin_notices.send(
                "⚠️ 赛尔图片素材获取失败\n"
                f"执行机器人：{identity.describe() if identity else '未确定'}\n"
                + "\n".join(lines)
                + outcome,
                subscription_key="render_crash_notice",
                action_name="Seer image source failure notice",
            )
        except Exception:
            logger.exception(
                "failed to deliver Seer image source failure notice: count=%s",
                len(failures),
            )
