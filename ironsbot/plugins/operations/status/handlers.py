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

from ironsbot.runtime.conversations import enter_event_reply_conversation
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

DOCKER_MAINTENANCE_NAMESPACE = "docker_maintenance"
DOCKER_MAINTENANCE_MENU = """请选择机器人维护操作：
1. 仅重启机器人
2. 更新镜像并重启机器人
0.【退出】

输入序号后会立即执行。"""


def _is_docker_maintenance_reply(event: MessageEvent) -> bool:
    return event.get_plaintext().strip() in {"0", "1", "2"}


async def _handle_docker_maintenance_action(
    matcher: Matcher,
    event: MessageEvent,
    *,
    docker_service: DockerUpdateService,
) -> None:
    choice = event.get_plaintext().strip()
    if choice == "0":
        await finish_event_reply(matcher, event, "已退出机器人维护。")
        return
    if choice == "1":
        message, restart_action = await docker_service.prepare_restart_only()
    elif choice == "2":
        message, restart_action = await docker_service.prepare_update_and_restart()
    else:
        await finish_event_reply(
            matcher,
            event,
            "⚠️ 序号超出范围，请重新输入；输入 0 退出。",
        )
        return
    await send_event_reply(matcher, event, message)
    await docker_service.execute_restart(restart_action)


async def _open_docker_maintenance_menu(
    matcher: Matcher,
    event: MessageEvent,
    *,
    docker_service: DockerUpdateService,
    check_image: bool = False,
) -> None:
    check_message = (
        await docker_service.check_image_update()
        if check_image
        else ""
    )
    prompt = (
        f"{check_message}\n\n{DOCKER_MAINTENANCE_MENU}"
        if check_message
        else DOCKER_MAINTENANCE_MENU
    )
    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=DOCKER_MAINTENANCE_NAMESPACE,
        handlers=[
            bind_async(
                _handle_docker_maintenance_action,
                docker_service=docker_service,
            )
        ],
        reply_check=_is_docker_maintenance_reply,
        prompt=prompt,
    )


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
    restart_matcher.append_handler(
        bind_async(
            _open_docker_maintenance_menu,
            docker_service=docker_service,
        )
    )

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
    update_matcher.append_handler(
        bind_async(
            _open_docker_maintenance_menu,
            docker_service=docker_service,
            check_image=True,
        )
    )
