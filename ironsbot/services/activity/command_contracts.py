# SPDX-License-Identifier: MIT
"""Platform-neutral command contracts for activity queries."""

from __future__ import annotations

from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandDescriptor,
    commands_from_rows,
)
from ironsbot.services.activity.commands import (
    CURRENT_ACTIVITY_COMMANDS,
    SOON_ENDING_ACTIVITY_COMMANDS,
)


def activity_command_descriptors() -> tuple[CommandDescriptor, ...]:
    """Describe direct activity commands for the shared command catalog."""

    return (
        *commands_from_rows(
            "activity",
            "查询",
            "seer_activity_query",
            (
                (
                    "activity.ending",
                    SOON_ENDING_ACTIVITY_COMMANDS[:1],
                    "查询即将结束的活动",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *commands_from_rows(
            "activity",
            "超级管理员",
            "seer_activity_query",
            (
                (
                    "activity.current",
                    tuple(f"/{command}" for command in CURRENT_ACTIVITY_COMMANDS[:1]),
                    "查询完整活动列表",
                    {"access": (CommandAccess(audience="superuser"),)},
                ),
            ),
        ),
    )
