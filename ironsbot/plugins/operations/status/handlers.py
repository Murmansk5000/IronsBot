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

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind_async
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import no_reply

from .command_text import (
    ADMIN_SERVER_STATUS_COMMAND,
    BOT_RESTART_COMMANDS,
    DISABLED_BARE_ADMIN_COMMAND,
    DOCKER_CHECK_UPDATE_COMMANDS,
    DOCKER_UPDATE_COMMANDS,
    NORMAL_SERVER_STATUS_COMMAND,
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
    await finish_event_reply(
        matcher,
        event,
        "“开服查询”仅限超级管理员，且必须带 / 前缀。"
        f"\n{commands.format_for(event, features, plugin_id='server_status')}",
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

    async def handle_check_image_update(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        await finish_event_reply(
            matcher,
            event,
            await docker_service.check_image_update(),
        )

    normal_matcher = registry.on_fullmatch(
        NORMAL_SERVER_STATUS_COMMAND,
        policy=CommandPolicy.command("server_status_query"),
        rule=no_reply(),
        priority=registry.priority("server_status"),
        block=True,
    )
    normal_matcher.append_handler(handle_normal_server_status)

    disabled_matcher = registry.on_fullmatch(
        DISABLED_BARE_ADMIN_COMMAND,
        policy=CommandPolicy.command("server_status_query"),
        rule=no_reply(),
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
        policy=CommandPolicy.command("server_status_admin"),
        rule=no_reply(),
        permission=SUPERUSER,
        priority=registry.priority("server_status_admin"),
        block=True,
    )
    admin_matcher.append_handler(handle_admin_server_status)

    restart_matcher = registry.on_fullmatch(
        BOT_RESTART_COMMANDS,
        policy=CommandPolicy.command("bot_restart"),
        rule=no_reply(),
        permission=SUPERUSER,
        priority=registry.priority("server_status_admin"),
        block=True,
    )
    restart_matcher.append_handler(handle_restart)

    update_matcher = registry.on_fullmatch(
        DOCKER_UPDATE_COMMANDS,
        policy=CommandPolicy.command("bot_restart"),
        rule=no_reply(),
        permission=SUPERUSER,
        priority=registry.priority("server_status_admin"),
        block=True,
    )
    update_matcher.append_handler(handle_restart)

    check_update_matcher = registry.on_fullmatch(
        DOCKER_CHECK_UPDATE_COMMANDS,
        policy=CommandPolicy.command("bot_restart"),
        rule=no_reply(),
        permission=SUPERUSER,
        priority=registry.priority("server_status_admin"),
        block=True,
    )
    check_update_matcher.append_handler(handle_check_image_update)
