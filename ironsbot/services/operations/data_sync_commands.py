# SPDX-License-Identifier: MIT
"""Platform-neutral command contracts and parsing for data synchronization."""

from __future__ import annotations

from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandContract,
    commands_from_rows,
)
from ironsbot.core.commands import normalize_command_text

MANUAL_SYNC_COMMANDS = ("更新数据", "数据更新")
FORCE_MANUAL_SYNC_COMMANDS = ("强制更新数据", "强制数据更新")
ADMIN_COMMAND_PREFIX = "/"
_NORMALIZED_MANUAL_SYNC_COMMANDS = frozenset(
    normalize_command_text(command) for command in MANUAL_SYNC_COMMANDS
)
_NORMALIZED_FORCE_MANUAL_SYNC_COMMANDS = frozenset(
    normalize_command_text(command) for command in FORCE_MANUAL_SYNC_COMMANDS
)


def data_sync_command_contracts() -> tuple[CommandContract, ...]:
    """Describe direct data-sync commands for the shared command catalog."""

    return commands_from_rows(
        "db_sync",
        "超级管理员",
        None,
        (
            (
                "db_sync.update",
                tuple(f"/{command}" for command in MANUAL_SYNC_COMMANDS),
                "检查后选择同步已发布数据，或构建上游数据后同步",
                {"access": (CommandAccess(audience="superuser"),)},
            ),
            (
                "db_sync.force_update",
                tuple(f"/{command}" for command in FORCE_MANUAL_SYNC_COMMANDS),
                "选择第 2 项时强制重建上游数据后同步",
                {"access": (CommandAccess(audience="superuser"),)},
            ),
        ),
    )


def is_manual_data_sync_command(text: str) -> bool:
    """Return whether text is one of the explicit data-sync commands."""

    normalized = _normalized_command(text)
    return normalized in (
        _NORMALIZED_MANUAL_SYNC_COMMANDS | _NORMALIZED_FORCE_MANUAL_SYNC_COMMANDS
    )


def is_force_data_sync_command(text: str) -> bool:
    """Return whether text requests a forced data synchronization."""

    return _normalized_command(text) in _NORMALIZED_FORCE_MANUAL_SYNC_COMMANDS


def _normalized_command(text: str) -> str:
    normalized = text.strip()
    if not normalized.startswith(ADMIN_COMMAND_PREFIX):
        return ""
    return normalize_command_text(normalized[len(ADMIN_COMMAND_PREFIX) :])
