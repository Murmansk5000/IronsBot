# SPDX-License-Identifier: MIT
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.integrations.onebot.message_rendering import (
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.replies import finish_event_reply
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.about import AboutService, about_command_contracts
from ironsbot.services.official_identity_info import (
    official_identity_info_command_contracts,
)

__plugin_meta__ = PluginMetadata(
    name="关于",
    description="显示 IronsBot 项目、版本与鸣谢信息。",
    usage="发送“关于”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

def install(registry: MatcherFactory, service: AboutService) -> None:
    async def handle_about(matcher: Matcher, event: MessageEvent) -> None:
        await finish_event_reply(
            matcher,
            event=event,
            message=render_onebot_outbound_message(service.message()),
        )

    matcher = registry.on_fullmatch(
        "关于",
        policy=CommandPolicy.command("about", help_ids=("about",)),
        rule=explicit_command(),
        priority=registry.priority("about"),
        block=True,
    )
    matcher.append_handler(handle_about)


def plugin_contribution(service: AboutService) -> PluginContribution:
    """Declare the complete runtime contribution owned by this top-level plugin."""

    return PluginContribution(
        id="about",
        features=frozenset({Feature.ABOUT, Feature.QQ_OFFICIAL_IDENTITY_INFO}),
        help=HelpEntry(
            name="关于",
            description="IronsBot 项目信息与当前版本",
            group="core",
            order=20,
        ),
        commands=(
            *about_command_contracts(),
            *official_identity_info_command_contracts(),
        ),
        install=lambda registry: install(registry, service),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(__plugin_meta__, plugin_contribution(context.resources.about))
