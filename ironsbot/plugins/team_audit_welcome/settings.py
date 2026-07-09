# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.config.loader import get_app_config
from ironsbot.shared.features import resolve_group_refs
from ironsbot.shared.messaging.text import build_message, render_text

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message

    from ironsbot.services.team_audit_welcome import TeamAuditPendingReminder

TEAM_AUDIT_FOLLOWUP_JOB_PREFIX = "team_audit_followup_"
FOLLOWUP_SCAN_INTERVAL_MINUTES = 10
FIRST_FOLLOWUP_STEP = 1
FINAL_FOLLOWUP_STEP = 2


def target_groups() -> set[int]:
    config = get_app_config().message.team_audit_welcome
    return set(resolve_group_refs(config.groups))


def welcome_message(user_id: int) -> Message:
    config = get_app_config().message.team_audit_welcome
    return build_message(render_text(config.message), at_user_ids=[user_id])


def followup_message(
    user_id: int,
    *,
    group_id: int,
    reminder: TeamAuditPendingReminder,
) -> Message:
    config = get_app_config().message.team_audit_welcome
    is_final = reminder.step >= FINAL_FOLLOWUP_STEP
    template = render_text(
        config.final_followup_message if is_final else config.followup_message
    )
    hours = (
        config.final_followup_after_hours if is_final else config.followup_after_hours
    )
    try:
        text = template.format(
            hours=hours,
            group_id=group_id,
            user_id=user_id,
        )
    except (IndexError, KeyError, ValueError):
        text = template
    return build_message(text, at_user_ids=[user_id])


def followup_cache_path() -> str:
    return get_app_config().message.team_audit_welcome.followup_cache_path


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "FINAL_FOLLOWUP_STEP",
    "FIRST_FOLLOWUP_STEP",
    "FOLLOWUP_SCAN_INTERVAL_MINUTES",
    "TEAM_AUDIT_FOLLOWUP_JOB_PREFIX",
    "followup_cache_path",
    "followup_message",
    "now_utc",
    "target_groups",
    "welcome_message",
]
