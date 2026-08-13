# SPDX-License-Identifier: MIT
"""Command contract owned by the project information domain."""

from __future__ import annotations

from ironsbot.core.command_catalog import CommandContract


def about_command_contracts() -> tuple[CommandContract, ...]:
    """Describe the direct project information command."""

    return (
        CommandContract(
            id="about",
            plugin_id="about",
            section="查看",
            examples=("关于",),
            description="查看项目、版本和主要能力",
            features_any=("about",),
        ),
    )
