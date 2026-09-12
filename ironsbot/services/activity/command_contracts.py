# SPDX-License-Identifier: MIT
"""Platform-neutral command contracts for activity queries."""

from __future__ import annotations

from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandContract,
    commands_from_rows,
)
from ironsbot.services.activity.commands import (
    CURRENT_ACTIVITY_COMMANDS,
    NEW_ACTIVITY_COMMANDS,
    SOON_ENDING_ACTIVITY_COMMANDS,
    is_current_seer_activity_text,
    is_new_seer_activity_text,
    is_soon_ending_seer_activity_text,
)


def activity_command_contracts() -> tuple[CommandContract, ...]:
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
                    {
                        "show_in_poke": True,
                        "routing_matcher": lambda text, _context: (
                            is_soon_ending_seer_activity_text(text)
                        ),
                    },
                ),
                (
                    "activity.new",
                    NEW_ACTIVITY_COMMANDS[:1],
                    "查询本周新增活动",
                    {
                        "routing_matcher": lambda text, _context: (
                            is_new_seer_activity_text(text)
                        ),
                    },
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
                    {
                        "access": (CommandAccess(audience="superuser"),),
                        "routing_matcher": lambda text, _context: (
                            is_current_seer_activity_text(text)
                        ),
                    },
                ),
            ),
        ),
    )
