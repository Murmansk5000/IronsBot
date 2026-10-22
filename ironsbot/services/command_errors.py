# SPDX-License-Identifier: MIT
"""Safe command failures and restricted operational notices for both transports."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import PurePath
from traceback import extract_tb
from typing import TYPE_CHECKING, Literal

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.messaging.rate_limits import SlidingWindowRateLimiter
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.portable_reply import ExecutionFailureStage

logger = logging.getLogger(__name__)
COMMAND_FAILED_MESSAGE = "❌ 命令执行失败，请稍后再试。"
_NOTICE_WINDOW_SECONDS = 60.0
_NOTICE_TIMEOUT_SECONDS = 5.0


@dataclass(slots=True)
class CommandErrorReporter:
    admin_notices: AdminNoticeService | None = None
    _limiter: SlidingWindowRateLimiter = field(default_factory=SlidingWindowRateLimiter)

    async def reply(
        self, context: MessageInputContext, error: Exception
    ) -> OutboundMessage:
        if isinstance(error, DataUnavailableError):
            return OutboundMessage.from_text(
                DATABASE_UNAVAILABLE_MESSAGE, request_succeeded=False
            )
        await self.report(context, error)
        return OutboundMessage.from_text(
            COMMAND_FAILED_MESSAGE, request_succeeded=False
        )

    async def report(
        self,
        context: MessageInputContext | CommandContext,
        error: Exception,
        stage: ExecutionFailureStage | Literal["operation", "notice"] = "operation",
    ) -> None:
        frames = extract_tb(error.__traceback__)
        frame = frames[-1] if frames else None
        location = (
            f"{PurePath(frame.filename).name}:{frame.lineno}:{frame.name}"
            if frame is not None
            else "unknown"
        )
        platform = (
            context.message.platform
            if isinstance(context, MessageInputContext)
            else context.conversation.platform
        ).value
        kind = (
            context.message.conversation
            if isinstance(context, MessageInputContext)
            else context.conversation
        ).kind
        error_type = type(error).__name__
        logger.error(
            "Command failed: platform=%s kind=%s stage=%s error_type=%s location=%s",
            platform,
            kind,
            stage,
            error_type,
            location,
        )
        if (
            self.admin_notices is not None
            and self._limiter.hit(
                "command_error_notice",
                (platform, stage, error_type, location),
                window_seconds=_NOTICE_WINDOW_SECONDS,
                max_events=1,
            )
            >= 0
        ):
            try:
                async with asyncio.timeout(_NOTICE_TIMEOUT_SECONDS):
                    await self.admin_notices.send(
                        "⚠️ 指令处理异常\n"
                        f"平台：{platform}\n会话类型：{kind}\n阶段：{stage}\n"
                        f"异常类型：{error_type}\n代码位置：{location}",
                        subscription_key="command_error_notice",
                        action_name="Command failure notice",
                    )
            except Exception as notice_error:  # noqa: BLE001 - no recursive notices
                logger.error(  # noqa: TRY400 - do not log delivery credentials
                    "Command failure notice failed: error_type=%s",
                    type(notice_error).__name__,
                )
