# SPDX-License-Identifier: MIT
"""Command descriptors owned by the configured image plugin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.messaging import FIXED_IMAGE_COMMANDS
from ironsbot.runtime.commands import CommandDescriptor

if TYPE_CHECKING:
    from ironsbot.services.messaging.sendpic import SendpicService


def command_descriptors(
    service: SendpicService,
) -> tuple[CommandDescriptor, ...]:
    """Describe exactly the image commands installed by this plugin."""

    fixed = tuple(
        CommandDescriptor(
            id=f"sendpic.fixed.{command}",
            plugin_id="sendpic",
            section="固定图片",
            examples=(command,),
            description="发送固定图片",
            features_any=("image",),
            show_in_poke=True,
        )
        for command in FIXED_IMAGE_COMMANDS
    )
    configured = tuple(
        CommandDescriptor(
            id=f"sendpic.{config.id}",
            plugin_id="sendpic",
            section="自定义图片",
            examples=(config.command, *sorted(config.aliases)),
            description="发送配置的图片；可在命令后附加编号",
            features_any=("image",),
            show_in_poke=True,
        )
        for config in service.commands
    )
    return (*fixed, *configured)
