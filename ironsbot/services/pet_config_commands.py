# SPDX-License-Identifier: MIT
"""Command contracts owned by the pet-configuration query domain."""

from __future__ import annotations

from functools import partial

from ironsbot.core.affix_commands import AffixCommand
from ironsbot.core.command_catalog import CommandContract, parsed_command_input_matcher
from ironsbot.services.seer.query_commands import is_reserved_query


def pet_config_input(image_commands: frozenset[str] = frozenset()) -> AffixCommand:
    return AffixCommand(
        ("精灵配置", "配置"),
        ("配置",),
        reject=partial(is_reserved_query, image_commands=image_commands),
    )


def pet_config_command_contracts(
    *, enabled: bool, image_commands: frozenset[str] = frozenset()
) -> tuple[CommandContract, ...]:
    """Describe direct pet-configuration commands when the domain is enabled."""

    if not enabled:
        return ()
    return (
        CommandContract(
            id="pet_config.query",
            plugin_id="pet_config",
            section="查询",
            examples=("雷伊配置", "配置雷伊", "4923配置"),
            description="查询已收录的精灵配置图",
            features_any=("pet_config",),
            show_in_poke=True,
            routing_matcher=parsed_command_input_matcher(
                pet_config_input(image_commands)
            ),
        ),
    )
