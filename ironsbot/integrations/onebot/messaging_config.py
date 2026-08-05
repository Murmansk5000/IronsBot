# SPDX-License-Identifier: MIT
"""Compile OneBot-specific message configuration into typed schedule targets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.messaging.targets import MessageScheduleTargets

if TYPE_CHECKING:
    from ironsbot.config.models.messaging import MessageConfig
    from ironsbot.core.onebot_references import OneBotReferenceResolver


def build_onebot_message_schedule_targets(
    config: MessageConfig,
    references: OneBotReferenceResolver,
) -> MessageScheduleTargets:
    """Resolve configured QQ mentions before messaging services schedule work."""

    return MessageScheduleTargets(
        group_mentions=tuple(
            tuple(
                references.actor_refs(
                    schedule.at_user_ids,
                    location=(f"messaging.schedules[{index}].at_user_ids"),
                )
            )
            for index, schedule in enumerate(config.schedules)
        )
    )
