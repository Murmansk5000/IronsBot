# SPDX-License-Identifier: MIT
"""Command contract owned by the interactive help domain."""

from __future__ import annotations

from ironsbot.core.command_catalog import CommandContract


def help_command_contracts() -> tuple[CommandContract, ...]:
    """Describe the direct interactive help command."""

    return (
        CommandContract(
            id="help",
            plugin_id="help",
            section="查看",
            examples=("帮助",),
            description="查看当前会话可用功能",
            features_any=("help",),
            show_in_poke=True,
        ),
    )
