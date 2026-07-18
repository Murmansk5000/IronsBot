# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from nonebot import logger

from ironsbot.shared.features import (
    groups_for_feature,
    is_superuser,
    users_for_feature,
    users_with_superusers,
)
from ironsbot.shared.messaging import send_broadcast_message
from ironsbot.shared.promotions import append_fire_manual_ad_for_group

from .notice import DEFAULT_START_TIME, DEFAULT_UPDATE_WEEKDAY

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent

    from ironsbot.config.models.runtime import ServerStatusConfig


@dataclass(slots=True)
class OpenBroadcast:
    config: ServerStatusConfig
    last_at: datetime | None = None

    async def send(self, event: MessageEvent, *, now: datetime) -> None:
        if not self.config.broadcast:
            logger.info("server status open broadcast skipped: disabled")
            return

        if not should_broadcast_opened(now):
            return

        group_ids = groups_for_feature("server_status_push")
        user_ids = users_with_superusers(users_for_feature("server_status_push"))
        if not group_ids and not user_ids:
            logger.info("server status open broadcast skipped: no targets")
            return

        if not can_trigger_open_broadcast(
            event,
            group_ids=group_ids,
            user_ids=user_ids,
        ):
            logger.info("server status open broadcast skipped: trigger not allowed")
            return

        if self._in_cooldown(now):
            logger.info("server status open broadcast skipped: cooldown")
            return

        summary = await send_broadcast_message(
            self.config.broadcast_message,
            group_ids=group_ids,
            private_user_ids=user_ids,
            action_name="server status open broadcast",
            interval_seconds=1.2,
            message_limiter=append_fire_manual_ad_for_group,
            subscription_key="server_status_push",
        )
        if summary.succeeded:
            self.last_at = now

    def _in_cooldown(self, now: datetime) -> bool:
        if self.last_at is None:
            return False

        cooldown_minutes = self.config.broadcast_cooldown_minutes
        return cooldown_minutes > 0 and now - self.last_at < timedelta(
            minutes=cooldown_minutes
        )


def should_broadcast_opened(now: datetime) -> bool:
    return now.weekday() == DEFAULT_UPDATE_WEEKDAY and now.time() >= DEFAULT_START_TIME


def can_trigger_open_broadcast(
    event: MessageEvent,
    *,
    group_ids: list[int],
    user_ids: list[int],
) -> bool:
    if is_superuser(event.user_id):
        return True

    group_id = getattr(event, "group_id", None)
    if group_id is not None:
        return int(group_id) in group_ids

    return event.user_id in user_ids
