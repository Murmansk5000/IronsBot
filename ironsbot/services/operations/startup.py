# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.services.messaging.admin_notice import AdminNoticeService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StartupNoticePart:
    subscription_key: str
    action_name: str
    message: str
    superusers_only: bool = False


@dataclass(slots=True)
class StartupNoticeService:
    admin_notices: AdminNoticeService
    parts: list[StartupNoticePart] = field(default_factory=list)
    sent: bool = False
    sending: bool = False
    pending: list[StartupNoticePart] = field(default_factory=list)
    ready: bool = False
    _pending_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def publish(
        self,
        subscription_key: str,
        action_name: str,
        message: str,
        *,
        superusers_only: bool = False,
    ) -> None:
        async with self._pending_lock:
            if not self.ready:
                self.pending.append(
                    StartupNoticePart(
                        subscription_key, action_name, message, superusers_only
                    )
                )
                return
        await self.admin_notices.send(
            message,
            subscription_key=subscription_key,
            action_name=action_name,
            superusers_only=superusers_only,
        )

    async def flush_pending(self) -> None:
        async with self._pending_lock:
            self.ready = True
            pending, self.pending = self.pending, []
            for part in pending:
                try:
                    await self.admin_notices.send(
                        part.message,
                        subscription_key=part.subscription_key,
                        action_name=part.action_name,
                        superusers_only=part.superusers_only,
                    )
                except Exception:  # noqa: PERF203 - notify remaining independent events
                    logger.exception("Queued data update notification failed")

    def add(self, subscription_key: str, action_name: str, message: str | None) -> None:
        if message:
            self.parts.append(
                StartupNoticePart(
                    subscription_key=subscription_key,
                    action_name=action_name,
                    message=message,
                )
            )

    def should_send(self, *, enabled: bool) -> bool:
        return enabled and not self.sent and not self.sending

    def begin_send(self) -> None:
        self.sending = True

    def mark_result(self, succeeded: Sequence[object]) -> None:
        if succeeded:
            self.sent = True

    def finish_send(self) -> None:
        self.sending = False
