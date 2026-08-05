# SPDX-License-Identifier: MIT
"""Command descriptors owned by the configured image plugin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import CommandDescriptor

if TYPE_CHECKING:
    from ironsbot.services.messaging.sendpic import SendpicService


def command_descriptors(
    service: SendpicService,
) -> tuple[CommandDescriptor, ...]:
    """Describe exactly the image commands installed by this plugin."""

    return tuple(
        CommandDescriptor(
            id=f"sendpic.{config.id}",
            plugin_id="sendpic",
            section="图片",
            examples=(config.command, *sorted(config.aliases)),
            description=(
                "发送配置的图片；可在命令后附加编号"
                if config.mode == "indexed"
                else "发送配置的图片"
            ),
            features_any=("image",),
            show_in_poke=True,
        )
        for config in service.commands
    )
