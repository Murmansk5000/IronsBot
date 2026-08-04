# SPDX-License-Identifier: MIT
# ruff: noqa: TC002
"""OneBot handlers and manifest contribution for server-status commands."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

from ironsbot.app.command_directory.rows import commands_from_rows
from ironsbot.core.features import Feature
from ironsbot.runtime.commands import CommandAccess, CommandDescriptor
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind_async
from ironsbot.runtime.onebot_context import command_context
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import explicit_command

from .status.command_text import (
    ADMIN_SERVER_STATUS_COMMAND,
    DISABLED_BARE_ADMIN_COMMAND,
    HEADLESS_INSTANCE_STATUS_COMMANDS,
    NORMAL_SERVER_STATUS_COMMAND,
)
from .status.commands import handle_admin_status, handle_normal_status

if TYPE_CHECKING:
    from ironsbot.core.features import FeatureService
    from ironsbot.runtime.commands import CommandCatalog
    from ironsbot.services.operations.server_status import ServerStatusService

__plugin_meta__ = PluginMetadata(
    name="开服查询",
    description="查询维护公告与无头客户端游戏连接状态。",
    usage="发送“开服了吗”查询；超级管理员可发送“/开服查询”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def command_descriptors() -> tuple[CommandDescriptor, ...]:
    return (
        *commands_from_rows(
            "server_status",
            "查询",
            "server_status_query",
            (
                (
                    "server_status.query",
                    (NORMAL_SERVER_STATUS_COMMAND,),
                    "查询当前维护和开服状态",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *commands_from_rows(
            "server_status",
            "超级管理员",
            None,
            (
                (
                    "server_status.admin_query",
                    (ADMIN_SERVER_STATUS_COMMAND,),
                    "查询开服状态，并在无头未登录时尝试重连",
                    {
                        "features_any": ("server_status_query",),
                        "access": (CommandAccess(audience="superuser"),),
                    },
                ),
                (
                    "server_status.headless_instances",
                    HEADLESS_INSTANCE_STATUS_COMMANDS,
                    "查看公共查询池与临时专用会话的当前在线实例数",
                    {"access": (CommandAccess(scope="private", audience="superuser"),)},
                ),
            ),
        ),
    )


async def _handle_disabled_bare_admin_status(
    matcher: Matcher,
    event: MessageEvent,
    *,
    commands: CommandCatalog,
    features: FeatureService,
) -> None:
    command_help = commands.format_for_context(
        command_context(event),
        features,
        plugin_id="server_status",
    )
    await finish_event_reply(
        matcher,
        event,
        f"“开服查询”仅限超级管理员，且必须带 / 前缀。\n{command_help}",
    )


def _install(
    registry: MatcherRegistry,
    server_status: ServerStatusService,
    features: FeatureService,
    commands: CommandCatalog,
) -> None:
    async def handle_normal_server_status(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        await handle_normal_status(
            matcher,
            event,
            features,
            server_status,
        )

    async def handle_admin_server_status(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        await handle_admin_status(
            matcher,
            event,
            server_status,
        )

    async def handle_headless_instance_status(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        await finish_event_reply(
            matcher,
            event,
            (await server_status.query_headless_instances()).message,
        )

    normal_matcher = registry.on_fullmatch(
        NORMAL_SERVER_STATUS_COMMAND,
        policy=CommandPolicy.command(
            "server_status_query",
            help_ids=("server_status.query",),
        ),
        rule=explicit_command(),
        priority=registry.priority("server_status"),
        block=True,
    )
    normal_matcher.append_handler(handle_normal_server_status)

    disabled_matcher = registry.on_fullmatch(
        DISABLED_BARE_ADMIN_COMMAND,
        policy=CommandPolicy.command(
            "server_status_query",
            help_ids=("server_status.admin_query",),
        ),
        rule=explicit_command(),
        priority=registry.priority("server_status"),
        block=True,
    )
    disabled_matcher.append_handler(
        bind_async(
            _handle_disabled_bare_admin_status,
            commands=commands,
            features=features,
        )
    )

    admin_matcher = registry.on_fullmatch(
        ADMIN_SERVER_STATUS_COMMAND,
        policy=CommandPolicy.command(
            "server_status_admin",
            help_ids=("server_status.admin_query",),
        ),
        rule=explicit_command(),
        permission=SUPERUSER,
        priority=registry.priority("server_status_admin"),
        block=True,
    )
    admin_matcher.append_handler(handle_admin_server_status)

    headless_status_matcher = registry.on_fullmatch(
        HEADLESS_INSTANCE_STATUS_COMMANDS,
        policy=CommandPolicy.command(
            "headless_instance_status",
            help_ids=("server_status.headless_instances",),
        ),
        rule=explicit_command(),
        permission=SUPERUSER,
        priority=registry.priority("server_status_admin"),
        block=True,
    )
    headless_status_matcher.append_handler(handle_headless_instance_status)


def plugin_contribution(
    *,
    service: ServerStatusService,
    features: FeatureService,
    commands: CommandCatalog,
) -> PluginContribution:
    """Declare server-status commands and feature ownership."""

    return PluginContribution(
        id="server_status",
        features=frozenset({Feature.SERVER_STATUS_QUERY}),
        help=HelpEntry(
            name="开服查询",
            description="查询赛尔号维护公告，并结合无头客户端连接状态判断是否已开服",
            group="seer",
            order=70,
            notes=(
                "无头客户端已登录游戏服务器时判定为已开服；公告仅作为维护信息摘要。",
            ),
        ),
        commands=command_descriptors(),
        install=partial(
            _install,
            server_status=service,
            features=features,
            commands=commands,
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.server_status,
            features=context.resources.features,
            commands=context.resources.commands,
        ),
    )
