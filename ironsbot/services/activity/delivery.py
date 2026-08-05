# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias

from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import ActorRef, ConversationRef

from .formatting import format_activity_list
from .planning import filter_valid_reminders

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime, timedelta

    from .models import ActivityInfo, ActivityReminder

DEFAULT_MESSAGE_TEMPLATE = "⏰ 本周活动将在约 {lead_hours} 小时后结束\n{activity_list}"
ActivityReminderDeliveryStatus = Literal["skip_empty", "skip_no_targets", "send"]
ActivityReminderRecipient: TypeAlias = ActorRef | ConversationRef
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ActivityReminderTargets:
    group_conversations: tuple[ConversationRef, ...] = ()
    private_actors: tuple[ActorRef, ...] = ()

    @property
    def has_targets(self) -> bool:
        return bool(self.group_conversations or self.private_actors)


@dataclass(frozen=True, slots=True)
class ActivityReminderDelivery:
    status: ActivityReminderDeliveryStatus
    message: OutboundMessage | None = None
    group_conversations: tuple[ConversationRef, ...] = ()
    private_actors: tuple[ActorRef, ...] = ()
    action_name: str = ""

    @property
    def should_send(self) -> bool:
        return self.status == "send"


class ActivityReminderSender(Protocol):
    """Platform adapter port for actively delivering an activity reminder."""

    async def send(self, reminder: ActivityReminderDelivery) -> bool: ...


def format_reminder_message(
    lead_hours: int,
    reminders: list[ActivityReminder],
    *,
    template: str,
    fallback_template: str = DEFAULT_MESSAGE_TEMPLATE,
) -> str:
    try:
        return template.format(
            lead_hours=lead_hours,
            activity_count=len(reminders),
            activity_list=format_activity_list(reminders),
        )
    except (KeyError, IndexError, ValueError) as exc:
        _LOGGER.warning("activity reminder template failed: %s", exc)
        return fallback_template.format(
            lead_hours=lead_hours,
            activity_list=format_activity_list(reminders),
        )


def build_reminder_delivery(
    lead_hours: int,
    reminders: list[ActivityReminder],
    targets: ActivityReminderTargets,
    *,
    template: str,
    fallback_template: str = DEFAULT_MESSAGE_TEMPLATE,
) -> ActivityReminderDelivery:
    if not reminders:
        return ActivityReminderDelivery(status="skip_empty")

    if not targets.has_targets:
        return ActivityReminderDelivery(status="skip_no_targets")

    return ActivityReminderDelivery(
        status="send",
        message=OutboundMessage(
            (
                TextPart(
                    format_reminder_message(
                        lead_hours,
                        reminders,
                        template=template,
                        fallback_template=fallback_template,
                    )
                ),
            )
        ),
        group_conversations=targets.group_conversations,
        private_actors=targets.private_actors,
        action_name=f"activity ending reminder {lead_hours}h",
    )


def filter_reminders_before_send(
    reminders: Iterable[ActivityReminder],
    *,
    now: datetime,
    current_activities: Iterable[ActivityInfo],
    dispatch_tolerance: timedelta,
    soon_ending_threshold: timedelta,
) -> list[ActivityReminder]:
    activity_by_id = {activity.activity_id: activity for activity in current_activities}
    return filter_valid_reminders(
        reminders,
        now=now,
        activity_by_id=activity_by_id,
        dispatch_tolerance=dispatch_tolerance,
        soon_ending_threshold=soon_ending_threshold,
    )
