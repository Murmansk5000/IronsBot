# SPDX-License-Identifier: MIT
"""Declarative entrypoint for configured image commands."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)

from .commands import command_descriptors

__plugin_meta__ = PluginMetadata(
    name="图片发送",
    description="发送固定图片或配置的图片库内容。",
    usage="发送已配置的图片口令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

if TYPE_CHECKING:
    from ironsbot.core.features import FeatureService
    from ironsbot.runtime.matchers import MatcherRegistry
    from ironsbot.services.messaging.sendpic import SendpicService


def _install(
    registry: MatcherRegistry,
    *,
    service: SendpicService,
    features: FeatureService,
) -> None:
    """Delay OneBot/SAA matcher imports until application installation."""

    from .matchers import install

    install(registry, service, features)


def plugin_contribution(
    *,
    service: SendpicService,
    features: FeatureService,
) -> PluginContribution:
    """Declare the commands and matcher installer owned by this plugin."""

    return PluginContribution(
        id="sendpic",
        features=frozenset({Feature.IMAGE}),
        help=HelpEntry(
            name="图片发送",
            description="发送固定图片或配置的图片库内容",
            group="other",
            order=20,
        ),
        commands=command_descriptors(service),
        install=partial(_install, service=service, features=features),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.sendpic,
            features=context.resources.features,
        ),
    )
