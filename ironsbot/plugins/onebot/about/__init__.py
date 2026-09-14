# SPDX-License-Identifier: MIT
from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    MatcherFactory,
    bind_async,
)
from ironsbot.integrations.onebot.replies import run_portable_operation
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.about import (
    AboutService,
    about_command_contracts,
    build_portable_about_operation,
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
    matcher = registry.on_fullmatch(
        "关于",
        policy=CommandPolicy.command("about", help_ids=("about",)),
        rule=explicit_command(),
        priority=registry.priority("about"),
        block=True,
    )
    matcher.append_handler(
        bind_async(
            run_portable_operation,
            operation=build_portable_about_operation(service),
        )
    )


def plugin_contribution(service: AboutService) -> PluginContribution:
    """Declare the complete runtime contribution owned by this top-level plugin."""

    return PluginContribution(
        id="about",
        features=frozenset({Feature.ABOUT}),
        help=HelpEntry(
            name="关于",
            description="IronsBot 项目信息与当前版本",
            group="core",
            order=20,
        ),
        commands=about_command_contracts(),
        install=lambda registry: install(registry, service),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(__plugin_meta__, plugin_contribution(context.resources.about))
