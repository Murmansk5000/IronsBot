# SPDX-License-Identifier: MIT
"""Compile configured logical groups and users into typed schedule targets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.message_schedule_targets import MessageScheduleTargets

if TYPE_CHECKING:
    from ironsbot.config.models.messaging import MessageConfig
    from ironsbot.config.qq_references import QQReferenceResolver


def build_message_schedule_targets(
    config: MessageConfig,
    references: QQReferenceResolver,
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
        ),
        group_targets=tuple(
            tuple(
                references.group_conversation_refs(
                    schedule.target_groups,
                    location=f"messaging.schedules[{index}].target_groups",
                )
            )
            for index, schedule in enumerate(config.schedules)
        ),
    )
