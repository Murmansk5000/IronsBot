# SPDX-License-Identifier: MIT
"""Command contracts owned by the pet-configuration query domain."""

from __future__ import annotations

from ironsbot.core.command_catalog import CommandDescriptor


def pet_config_command_descriptors(*, enabled: bool) -> tuple[CommandDescriptor, ...]:
    """Describe direct pet-configuration commands when the domain is enabled."""

    if not enabled:
        return ()
    return (
        CommandDescriptor(
            id="pet_config.query",
            plugin_id="pet_config",
            section="查询",
            examples=("雷伊配置", "配置雷伊", "4923配置"),
            description="查询已收录的精灵配置图",
            features_any=("pet_config",),
            show_in_poke=True,
        ),
    )
