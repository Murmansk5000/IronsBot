# SPDX-License-Identifier: MIT
# ruff: noqa: TC002
"""NoneBot handlers for server status commands.

NoneBot resolves handler annotations at registration time, so these annotation
imports must stay available at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.typing import T_State

from ironsbot.plugins.operations.update_confirmation import (
    UpdateConfirmation,
    request_update_confirmation,
)
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind_async
from ironsbot.runtime.onebot_context import command_context
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import explicit_command

from .command_text import (
    ADMIN_SERVER_STATUS_COMMAND,
    BOT_RESTART_COMMANDS,
    DISABLED_BARE_ADMIN_COMMAND,
    DOCKER_UPDATE_COMMANDS,
    HEADLESS_INSTANCE_STATUS_COMMANDS,
    NORMAL_SERVER_STATUS_COMMANDS,
)
from .commands import handle_admin_status, handle_normal_status

if TYPE_CHECKING:
    from ironsbot.core.features import FeatureService
    from ironsbot.runtime.commands import CommandCatalog
    from ironsbot.services.operations.docker_update import DockerUpdateService
    from ironsbot.services.operations.server_status import ServerStatusService


async def handle_disabled_bare_admin_status(
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
        "“开服查询”仅限超级管理员，且必须带 / 前缀。"
        f"\n{command_help}",
    )


def install(
    registry: MatcherRegistry,
    docker_service: DockerUpdateService,
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

    async def handle_restart(matcher: Matcher, event: MessageEvent) -> None:
        message, restart_action = await docker_service.prepare_manual_restart()
        await send_event_reply(matcher, event, message)
        await docker_service.execute_restart(restart_action)

    async def handle_headless_instance_status(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        await finish_event_reply(
            matcher,
            event,
            (await server_status.query_headless_instances()).message,
        )

    async def handle_image_update(matcher: Matcher, event: MessageEvent) -> None:
        message, should_update = await docker_service.prepare_manual_update()
        if not should_update:
            await finish_event_reply(matcher, event, message)
            return
        await request_update_confirmation(
            matcher,
            event,
            UpdateConfirmation(
                namespace="docker_update_confirmation",
                check_message=message,
                action_label="更新镜像并重启机器人",
                executor=run_confirmed_image_update,
            ),
        )

    async def run_confirmed_image_update(
        _matcher: Matcher,
        _event: MessageEvent,
        _state: T_State,
    ) -> str:
        return await docker_service.execute_manual_update()

    normal_matcher = registry.on_fullmatch(
        NORMAL_SERVER_STATUS_COMMANDS,
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
            handle_disabled_bare_admin_status,
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

    restart_matcher = registry.on_fullmatch(
        BOT_RESTART_COMMANDS,
        policy=CommandPolicy.command(
            "bot_restart",
            help_ids=("docker_update.restart",),
        ),
        rule=explicit_command(),
        permission=SUPERUSER,
        priority=registry.priority("server_status_admin"),
        block=True,
    )
    restart_matcher.append_handler(handle_restart)

    update_matcher = registry.on_fullmatch(
        DOCKER_UPDATE_COMMANDS,
        policy=CommandPolicy.command(
            "bot_restart",
            help_ids=("docker_update.image_update",),
        ),
        rule=explicit_command(),
        permission=SUPERUSER,
        priority=registry.priority("server_status_admin"),
        block=True,
    )
    update_matcher.append_handler(handle_image_update)
